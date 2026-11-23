"""
discover.py -- the open half of the vocabulary.

A module index is only as good as the module list it was given, and on a new estate
nobody knows that list yet. Worse, a closed list fails silently: tell the tool about
eight modules and it will happily attribute an estate that actually has ten, and the
two missing ones simply never appear. Nothing in the output says "we found Project
System everywhere and had nowhere to put it".

So this module does two jobs, and BOTH are part of a normal run:

  propose()   before attribution -- reads the scan and proposes the vocabulary from
              what is actually in the tree: packages and their short texts, the naming
              segments this estate really uses, standard tables and calls it really
              touches, prefix families it really has.

  register()  after attribution -- collects every rule hit that named a module with no
              tick column, with its evidence and example units, and asks for a
              decision: adopt as a core module, adopt as a cross-cutting bucket, or
              rule out with a reason.

Three ways out of a proposal, all explicit:
  adopt      modules.core += [...]  or  modules.buckets {...}   -> it gets a column
  rule out   modules.not_modules {"NAME": "why"}                -> silenced, on record
  blacklist  naming.segment_blacklist += [...]                  -> it was never a
             module, just a token that looks like one (entity code, plant, layer)

Doing nothing is also a decision, and it is the one the validator complains about --
by design.
"""

import collections
import csv
import json
import re

csv.field_size_limit(10_000_000)

SEG_MIN_COUNT = 8          # a segment seen fewer times than this is noise, not a rule
FAMILY_MIN_COUNT = 6
NAMEABLE_MIN_OBJECTS = 5


# --- inputs ---------------------------------------------------------------------------
def _load_signals(cfg):
    rows = []
    p = cfg.work("object_signals.tsv")
    if p.exists():
        with p.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
    return rows


def _load_packages(cfg):
    out = {}
    p = cfg.work("object_package_map.tsv")
    if p.exists():
        with p.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                out.setdefault(row["object_name"], row["package"])
    return out


def _load_stats(cfg):
    p = cfg.work("package_map_stats.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# --- proposal heuristics --------------------------------------------------------------
def _module_from_text(cfg, text):
    """Modules named or described in a free-text string (a package short text).

    'TG Development Package for QM' -> QM, evidence 'text names QM'.
    """
    if not text:
        return []
    t = f" {text.upper()} "
    hits = []
    for mod in sorted(set(cfg.nameable_modules) | set(cfg.all_modules)):
        if re.search(rf"[^A-Z0-9]{re.escape(mod)}[^A-Z0-9]", t):
            hits.append((mod, f"short text names {mod}"))
    for mod, kws in cfg.text_keywords.items():
        for kw in kws:
            if kw.upper() in t:
                hits.append((mod, f"short text: {kw.title()}"))
                break
    return hits


def _module_from_name(cfg, name):
    """Modules implied by the tokens of a package or object name."""
    hits = []
    for seg in str(name).upper().split("_"):
        if seg in cfg.segment_blacklist:
            continue
        if seg in cfg.token_map:
            hits.append((cfg.token_map[seg], f"name token {seg}"))
        elif seg.startswith(tuple(p.upper() for p in cfg.custom_prefixes)) \
                and seg[1:] in cfg.token_map:
            hits.append((cfg.token_map[seg[1:]], f"name token {seg}"))
    return hits


def _fingerprint(cfg, sig_rows):
    """Majority module from the standard tables and calls a set of objects touches."""
    from . import rules as R
    votes = collections.Counter()
    for row in sig_rows:
        for t in (row.get("std_tables") or "").split("|"):
            if t and t in cfg.table_to_module:
                votes[cfg.table_to_module[t]] += 1
        for c in (row.get("std_calls") or "").split("|"):
            mod = R.std_call_module(cfg, c) if c else None
            if mod:
                votes[mod] += 1
    return votes


def propose(cfg, verbose=True):
    """Propose the vocabulary and the maps from what is actually in the tree."""
    sig_rows = _load_signals(cfg)
    packages = _load_packages(cfg)
    stats = _load_stats(cfg)
    descriptions = {k.upper(): v for k, v in
                    (stats.get("package_descriptions") or {}).items()}

    by_pkg = collections.defaultdict(list)
    for row in sig_rows:
        pkg = packages.get(row["object_name"])
        if pkg:
            by_pkg[pkg].append(row)

    # --- 1. package -> module proposals ------------------------------------------------
    pkg_proposals = []
    for pkg, rows in sorted(by_pkg.items(), key=lambda kv: -len(kv[1])):
        if pkg in cfg.excluded_packages:
            continue
        # A package mapped to an EMPTY list is a decision already taken: "this package
        # carries no module signal". Generic team or default packages (a bare Z-prefix, a numbered team package,
        # $TMP) are exactly that, and nagging about them every run trains people to
        # ignore the report. It still shows in the deliverable, as a stated limit on
        # how far rule R1 can reach.
        mapped = pkg in cfg.package_modules
        current = cfg.package_modules.get(pkg)
        no_signal = mapped and not current
        ev = collections.defaultdict(list)
        for mod, why in _module_from_name(cfg, pkg):
            ev[mod].append(why)
        for mod, why in _module_from_text(cfg, descriptions.get(pkg, "")):
            ev[mod].append(why)
        fp = _fingerprint(cfg, rows)
        top = fp.most_common(3)
        for mod, n in top:
            if n >= max(3, 0.15 * sum(fp.values())):
                ev[mod].append(f"{n} standard-object hits")
        ranked = sorted(ev.items(), key=lambda kv: (-len(set(kv[1])), kv[0]))
        # A mapping is only safe to adopt unattended when ONE module is clearly ahead
        # and its evidence is not fingerprint-only. A package's objects reading another
        # module's tables proves traffic, not ownership -- an SD program reads MM tables
        # all day -- so a fingerprint on its own parks the decision for a human.
        confident = None
        if ranked:
            top, top_ev = ranked[0][0], sorted(set(ranked[0][1]))
            runner = len(set(ranked[1][1])) if len(ranked) > 1 else 0
            hard = [w for w in top_ev if not w.endswith("standard-object hits")]
            if len(top_ev) > runner and hard and cfg.in_vocab(top):
                confident = top
        pkg_proposals.append({
            "package": pkg,
            "objects": len(rows),
            "description": descriptions.get(pkg, ""),
            "current": current,
            "suggested": [m for m, _ in ranked[:3]],
            "evidence": {m: sorted(set(w)) for m, w in ranked[:3]},
            "in_vocabulary": [m for m, _ in ranked[:3] if cfg.in_vocab(m)],
            "confident": confident,
            "status": ("mapped" if current else
                       "no-module-signal (declared)" if no_signal else "UNMAPPED"),
        })

    # --- 2. naming segments this estate actually uses ----------------------------------
    seg_counts = collections.Counter()
    seg_examples = collections.defaultdict(list)
    prefixes = tuple(p.upper() for p in cfg.custom_prefixes)
    for row in sig_rows:
        name = row["object_name"].upper()
        if not name.startswith(prefixes):
            continue
        segs = name.split("_")
        for idx in cfg.module_segments:
            if idx < len(segs) and segs[idx]:
                seg = segs[idx]
                seg_counts[seg] += 1
                if len(seg_examples[seg]) < 4:
                    seg_examples[seg].append(name)
    unknown_segments = []
    for seg, n in seg_counts.most_common():
        if n < SEG_MIN_COUNT or seg in cfg.segment_blacklist or seg in cfg.token_map:
            continue
        if seg.isdigit():
            continue
        unknown_segments.append({"segment": seg, "objects": n,
                                 "examples": seg_examples[seg]})

    # --- 3. prefix families -------------------------------------------------------------
    fam_counts = collections.Counter()
    fam_examples = collections.defaultdict(list)
    for row in sig_rows:
        name = row["object_name"].upper()
        if not name.startswith(prefixes) or "_" not in name:
            continue
        head = "_".join(name.split("_")[:2]) + "_"
        fam_counts[head] += 1
        if len(fam_examples[head]) < 4:
            fam_examples[head].append(name)
    known_family_rx = [rx for rx, _m, _l in cfg.families]
    families = []
    for head, n in fam_counts.most_common(40):
        if n < FAMILY_MIN_COUNT:
            continue
        if any(rx.search(head) for rx in known_family_rx):
            continue
        rows = [r for r in sig_rows if r["object_name"].upper().startswith(head)]
        fp = _fingerprint(cfg, rows)
        families.append({"prefix": head, "objects": n,
                         "examples": fam_examples[head],
                         "fingerprint": dict(fp.most_common(3))})

    # --- 4. modules the estate touches but the config never names ----------------------
    fp_all = _fingerprint(cfg, sig_rows)
    per_module_objects = collections.Counter()
    for row in sig_rows:
        mods = set()
        for t in (row.get("std_tables") or "").split("|"):
            if t and t in cfg.table_to_module:
                mods.add(cfg.table_to_module[t])
        for mod in mods:
            per_module_objects[mod] += 1
    missing = []
    for mod, n in per_module_objects.most_common():
        if cfg.in_vocab(mod) or cfg.is_ruled_out(mod) or n < NAMEABLE_MIN_OBJECTS:
            continue
        tables = collections.Counter()
        examples = []
        for row in sig_rows:
            hit = [t for t in (row.get("std_tables") or "").split("|")
                   if t and cfg.table_to_module.get(t) == mod]
            if hit:
                tables.update(hit)
                if len(examples) < 5:
                    examples.append(row["object_name"])
        missing.append({"module": mod, "objects": n,
                        "label": cfg.labels.get(mod, mod),
                        "tables": dict(tables.most_common(6)),
                        "examples": examples,
                        "signal_hits": fp_all.get(mod, 0)})

    out = {
        "project": cfg.project,
        "vocabulary": {"core": cfg.core, "buckets": cfg.buckets,
                       "ruled_out": sorted(cfg.not_modules)},
        "packages": pkg_proposals,
        "unmapped_packages": [p for p in pkg_proposals if p["status"] == "UNMAPPED"],
        "unknown_segments": unknown_segments,
        "candidate_families": families,
        "modules_with_evidence_but_no_column": missing,
    }
    path = cfg.work("discovery.json")
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    if verbose:
        print(f"packages seen: {len(pkg_proposals)}  "
              f"(unmapped: {len(out['unmapped_packages'])})")
        for p in pkg_proposals:
            if p["status"] != "UNMAPPED":
                continue
            sugg = ", ".join(p["suggested"]) or "no suggestion"
            print(f"  {p['package']:<26} {p['objects']:>5} objects  -> {sugg}")
            if p["description"]:
                print(f"      short text: {p['description']}")
            for mod, why in p["evidence"].items():
                print(f"      {mod}: {'; '.join(why)}")
        if missing:
            print(f"\nmodules with evidence but NO tick column ({len(missing)}):")
            for m in missing:
                print(f"  {m['module']:<8} {m['objects']:>5} objects   tables: "
                      f"{', '.join(list(m['tables'])[:5])}")
        if unknown_segments:
            print(f"\nnaming segments not mapped and not blacklisted "
                  f"({len(unknown_segments)}) -- each is either a module, a bucket, or "
                  "an entity/layer code to blacklist:")
            for s in unknown_segments[:15]:
                print(f"  {s['segment']:<10} {s['objects']:>5} objects  e.g. "
                      f"{', '.join(s['examples'][:2])}")
        print(f"\nwrote {cfg.rel(path)}")
    return out


# --- post-attribution register --------------------------------------------------------
def register(cfg, verbose=True):
    """Aggregate proposals.tsv into a decision list, and write the discovery report."""
    path = cfg.work("proposals.tsv")
    rows = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))

    by_mod = collections.defaultdict(list)
    for r in rows:
        by_mod[r["proposed_module"]].append(r)

    register_rows = []
    for mod, rs in sorted(by_mod.items(), key=lambda kv: -len(kv[1])):
        authorities = collections.Counter(r["authority"] for r in rs)
        rules = collections.Counter(r["rule"] for r in rs)
        register_rows.append({
            "module": mod,
            "units": len(rs),
            "label": cfg.labels.get(mod, mod),
            "authorities": dict(authorities),
            "rules": dict(rules),
            "strongest": ("AUTHORITATIVE" if authorities.get("AUTHORITATIVE")
                          else "STRONG" if authorities.get("STRONG")
                          else "INFERRED" if authorities.get("INFERRED") else "WEAK"),
            "examples": [{"unit": r["unit_id"], "root": r["root_object"],
                          "role": r["role"], "evidence": r["evidence"]}
                         for r in rs[:6]],
        })

    disc = {}
    dpath = cfg.work("discovery.json")
    if dpath.exists():
        disc = json.loads(dpath.read_text(encoding="utf-8"))
    disc["proposed_modules"] = register_rows
    dpath.write_text(json.dumps(disc, indent=2, ensure_ascii=False), encoding="utf-8")

    md = write_report(cfg, disc)
    if verbose:
        if register_rows:
            print("proposed modules (evidence found, no tick column):")
            for r in register_rows:
                print(f"  {r['module']:<12} {r['units']:>5} units   "
                      f"strongest={r['strongest']}   rules="
                      f"{','.join(sorted(r['rules']))}")
        else:
            print("no out-of-vocabulary module evidence -- the configured vocabulary "
                  "covers everything the rules can name")
        print(f"wrote {cfg.rel(md)}")
    return register_rows


def write_report(cfg, disc):
    """The human-facing discovery report: every open decision, with its evidence."""
    L = [f"# Module Index — discovery and open decisions ({cfg.project})", "",
         "This report exists because the module vocabulary is **open**. Everything "
         "below is evidence the rules found and could not place, or a mapping nobody "
         "has confirmed yet. Each item has exactly three honest outcomes: adopt it, "
         "rule it out with a reason, or blacklist the token that produced it.", "",
         f"Current vocabulary — core: `{', '.join(cfg.core) or '(none)'}` · "
         f"buckets: `{', '.join(cfg.buckets) or '(none)'}`"
         + (f" · ruled out: `{', '.join(sorted(cfg.not_modules))}`"
            if cfg.not_modules else ""), ""]

    prop = disc.get("proposed_modules") or []
    L += ["## 1. Modules the rules named, with no tick column", ""]
    if not prop:
        L += ["None. Every module any rule fired for is in the vocabulary.", ""]
    else:
        L += ["| Module | Units | Strongest signal | Rules | Decide |",
              "|---|---:|---|---|---|"]
        for r in prop:
            L.append(f"| **{r['module']}** ({r['label']}) | {r['units']} | "
                     f"{r['strongest']} | {', '.join(sorted(r['rules']))} | "
                     "adopt / rule out |")
        L.append("")
        for r in prop:
            L += [f"### {r['module']} — {r['units']} units", ""]
            for ex in r["examples"]:
                L.append(f"- `{ex['root']}` ({ex['role']}) — {ex['evidence']}")
            mod = r["module"]
            L += ["", "Adopt as a core module:", "",
                  "```json", '"modules": { "core": [..., "' + mod + '"] }',
                  "```", "",
                  "Or rule it out, on the record:", "",
                  "```json",
                  '"modules": { "not_modules": { "' + mod
                  + '": "why this is not a module here" } }',
                  "```", ""]

    missing = disc.get("modules_with_evidence_but_no_column") or []
    L += ["## 2. Modules whose standard objects appear in the code", ""]
    if not missing:
        L += ["None beyond the configured vocabulary.", ""]
    else:
        L += ["These are reads and writes against another module's standard tables. "
              "That is not proof of ownership — an SD program reads MM tables all day "
              "— but a module with a large, exclusive footprint here is usually a real "
              "gap in the vocabulary.", "",
              "| Module | Objects touching it | Tables seen |", "|---|---:|---|"]
        for m in missing:
            L.append(f"| **{m['module']}** ({m['label']}) | {m['objects']} | "
                     f"`{'`, `'.join(list(m['tables'])[:6])}` |")
        L.append("")

    unmapped = disc.get("unmapped_packages") or []
    L += ["## 3. Packages with no module mapping", ""]
    if not unmapped:
        L += ["None — every package carrying objects is mapped.", ""]
    else:
        L += ["Rule R1 is the only AUTHORITATIVE signal in the ladder, and it cannot "
              "fire for an unmapped package. Every row here is attribution the index "
              "is doing the hard way.", "",
              "| Package | Objects | Package short text | Suggested | Why |",
              "|---|---:|---|---|---|"]
        for p in unmapped:
            why = "; ".join(f"{m}: {', '.join(w)}"
                            for m, w in list(p["evidence"].items())[:2])
            L.append(f"| `{p['package']}` | {p['objects']} | {p['description'] or '—'} "
                     f"| {', '.join(p['suggested']) or '—'} | {why or '—'} |")
        L += ["", "```json", '"packages": { "map": {',
              ",\n".join(f'  "{p["package"]}": '
                         f'{json.dumps(p["suggested"][:2] or ["?"])}'
                         for p in unmapped[:12]),
              "} }", "```", ""]

    segs = disc.get("unknown_segments") or []
    L += ["## 4. Naming segments that are neither mapped nor blacklisted", ""]
    if not segs:
        L += ["None above the noise floor.", ""]
    else:
        L += ["Each of these appears in a module position of many object names. A "
              "segment is one of three things: a module, a cross-cutting bucket, or an "
              "entity/plant/layer code that only looks like a module. The third kind "
              "MUST be blacklisted — an unfiltered token match smears it across the "
              "estate.", "",
              "| Segment | Objects | Examples |", "|---|---:|---|"]
        for s in segs[:25]:
            L.append(f"| `{s['segment']}` | {s['objects']} | "
                     f"`{'`, `'.join(s['examples'][:3])}` |")
        L += ["", "```json",
              '"naming": { "segment_blacklist": '
              + json.dumps([s["segment"] for s in segs[:10]]) + " }", "```", ""]

    fams = disc.get("candidate_families") or []
    if fams:
        L += ["## 5. Candidate families", "",
              "Prefix groups with no family rule. A family rule is the right tool when "
              "a whole prefix belongs to one area regardless of what its members are "
              "named (handheld scanning, e-invoicing, analytics).", "",
              "| Prefix | Objects | Standard-object fingerprint | Examples |",
              "|---|---:|---|---|"]
        for f in fams[:20]:
            fp = ", ".join(f"{k}:{v}" for k, v in f["fingerprint"].items()) or "—"
            L.append(f"| `{f['prefix']}` | {f['objects']} | {fp} | "
                     f"`{'`, `'.join(f['examples'][:2])}` |")
        L.append("")

    L += ["## How to close these", "",
          "1. Edit `module-index.config.json`.",
          "2. Re-run from the attribution step — `modindex.py run --from attribute`. "
          "Nothing re-reads the source tree, so it takes seconds.",
          "3. Re-read this report. It is regenerated every run, so an item that is "
          "still here is still open.", "",
          "An adopted module gets a tick column and joins the coverage checks. A "
          "ruled-out one is silenced with its reason recorded. Doing neither leaves "
          "the validator reporting it every run — which is the point.", ""]

    # The names the rules could not settle. A separate concern from the vocabulary
    # proposals above -- those ask "should this be a column", these ask "what IS this
    # standard object" -- but the same audience and the same report.
    from . import unresolved
    L += [""] + unresolved.report_lines(cfg)

    path = cfg.out("-discovery.md")
    path.write_text("\n".join(L), encoding="utf-8")
    return path
