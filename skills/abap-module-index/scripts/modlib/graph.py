"""
graph.py -- turn raw edges into a graph worth walking.

Three defects make a raw extraction unusable, and all three are silent:

  self-loops        a function group "including" its own LZ<name>TOP is not a
                    relationship, and it can be nearly every include-edge in a raw
                    extraction. The test must be EXACT, though: a loose prefix/substring
                    check also eats real edges -- ZC_..._0001 -> ZC_..._0001_BE (the
                    OData frontend/backend twin) and any ZXX_FOO -> ZXX_FOO_HELPER call
                    look like self-references to a substring test.
  third-party        open-source ABAP vendored into customer packages.
  per-call-site rows a class calling another on 40 lines appeared 40 times. A graph
                    wants distinct edges; evidence wants the call sites. Keep both --
                    first site plus an occurrence count.

Fan-in is computed once, here, so every downstream consumer uses the same number. It
is what the infrastructure gate in the attribution ladder keys on.

Outputs
  edges.csv    merged, deduplicated, with origin/first_site/occurrences
  fanin.tsv    in-degree per object
"""

import collections
import csv
import re

csv.field_size_limit(10_000_000)

# A function group's generated includes: LZFOOTOP, LZFOOUXX, LZFOOF01, LZFOO01.
_FUGR_INCLUDE_SUFFIX = re.compile(r"(TOP|UXX|[A-Z]{1,3}\d{2}|\d{2})?$")


def is_self_ref(src, tgt):
    if src == tgt:
        return True
    s, t = src.upper(), tgt.upper()
    if t == "SAPL" + s:
        return True
    if t.startswith("L") and t[1:].startswith(s):
        return bool(_FUGR_INCLUDE_SUFFIX.fullmatch(t[1 + len(s):]))
    return False


def build(cfg, verbose=True):
    edges = {}        # (src, src_type, edge_type, tgt) -> [tgt_type, origin, site, n]
    stats = collections.Counter()

    raw = cfg.work("edges_raw.csv")
    if not raw.exists():
        raise FileNotFoundError(f"{raw} missing -- run `scan` first")
    with raw.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            _add(cfg, edges, stats,
                 (row.get("source_object") or "").upper(),
                 (row.get("source_type") or "").upper(),
                 (row.get("edge_type") or "CALL").upper(),
                 (row.get("target_object") or "").upper(),
                 (row.get("target_type") or "").upper(),
                 row.get("origin") or "", row.get("evidence") or "")

    # Extra edge sources: anything another tool produced, same columns.
    for extra in cfg.data.get("extra_edge_files", []):
        path = cfg.root / extra
        if not path.exists():
            print(f"WARNING: extra_edge_files entry {extra} not found")
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                _add(cfg, edges, stats,
                     (row.get("source_object") or "").upper(),
                     (row.get("source_type") or "").upper(),
                     (row.get("edge_type") or "CALL").upper(),
                     (row.get("target_object") or "").upper(),
                     (row.get("target_type") or "").upper(),
                     "external", f"{extra}:{row.get('line', '')}")

    out = cfg.work("edges.csv")
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["source_object", "source_type", "edge_type", "target_object",
                    "target_type", "origin", "first_site", "occurrences"])
        for (src, stype, etype, tgt), (ttype, origin, site, n) in sorted(edges.items()):
            w.writerow([src, stype, etype, tgt, ttype, origin, site, n])

    fanin = collections.Counter()
    for (_src, _st, _et, tgt) in edges:
        fanin[tgt] += 1
    fpath = cfg.work("fanin.tsv")
    with fpath.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("object_name\tin_degree\n")
        for name, n in sorted(fanin.items(), key=lambda kv: (-kv[1], kv[0])):
            fh.write(f"{name}\t{n}\n")

    if verbose:
        print(f"merged edges: {len(edges)}")
        for k in ("dropped_third_party", "dropped_self_ref", "dropped_empty",
                  "dup_collapsed"):
            print(f"  {k:<22} {stats[k]}")
        by_origin = collections.Counter(v[1] for v in edges.values())
        print("  by origin: " + ", ".join(f"{k}={v}" for k, v in by_origin.most_common()))
        print("\ntop edge types:")
        for name, n in collections.Counter(k[2] for k in edges).most_common(14):
            print(f"  {name:<20} {n:>6}")
        gate = cfg.tuning["fanin_gate"]
        print(f"\ntop fan-in (infrastructure gate fires at >= {gate}):")
        for name, n in fanin.most_common(10):
            print(f"  {n:>4}  {name}")
        print(f"\nwrote {cfg.rel(out)}")
        print(f"wrote {cfg.rel(fpath)}")
    return {"edges": len(edges), "dropped": dict(stats),
            "gated_objects": sum(1 for n in fanin.values()
                                 if n >= cfg.tuning["fanin_gate"])}


def _add(cfg, edges, stats, src, stype, etype, tgt, ttype, origin, site):
    if not src or not tgt:
        stats["dropped_empty"] += 1
        return
    if cfg.is_third_party_name(src) or cfg.is_third_party_name(tgt):
        stats["dropped_third_party"] += 1
        return
    if is_self_ref(src, tgt):
        stats["dropped_self_ref"] += 1
        return
    key = (src, stype, etype, tgt)
    prev = edges.get(key)
    if prev is not None:
        stats["dup_collapsed"] += 1
        prev[0] = prev[0] or ttype
        prev[3] += 1
        return
    edges[key] = [ttype, origin, site, 1]


class Graph:
    def __init__(self):
        self.adj = collections.defaultdict(list)   # src -> [(edge_type, tgt, tgt_type)]
        self.fanin = collections.Counter()

    @classmethod
    def load(cls, cfg):
        g = cls()
        with cfg.work("edges.csv").open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                g.adj[row["source_object"]].append(
                    (row["edge_type"], row["target_object"],
                     row.get("target_type", "")))
        fpath = cfg.work("fanin.tsv")
        if fpath.exists():
            with fpath.open(encoding="utf-8") as fh:
                next(fh, None)
                for line in fh:
                    name, n = line.rstrip("\n").split("\t")
                    g.fanin[name] = int(n)
        return g
