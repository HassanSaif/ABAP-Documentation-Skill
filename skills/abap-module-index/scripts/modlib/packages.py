"""
packages.py -- object -> home package, from whatever this repository actually offers.

Why this is its own step: abapGit strips <DEVCLASS>, <AUTHOR> and transport data from
every object file, so an object NEVER states its own package. The home package is
nonetheless the single most reliable module signal there is (rule R1, AUTHORITATIVE),
because it is a decision a human made in SAP and a transport enforced. So it is worth
recovering from indirect evidence -- and worth admitting when it cannot be.

Providers, tried in configured order; the first to claim an object wins, later ones
fill gaps:

  tree   folder structure. `<PKG>/src/...` -> PKG; `src/<sub>/...` -> sub-package,
         resolved with the repo's own FOLDER_LOGIC from .abapgit.xml.
  zips   per-package abapGit export archives. Reads ZIP central directories only
         (namelist()), never extracts. This is the only source for a FLAT export,
         where the tree carries no package information whatsoever.
  csv    an explicit object -> package list (an SE80/ATC/register download).

Output
  object_package_map.tsv    (object_name, object_type, package, source)
  package_map_stats.json    reconciliation + held-out agreement, quoted by the
                            renderer so the numbers in the deliverable cannot go stale
"""

import collections
import csv
import json
import pathlib
import zipfile

from . import heldout as H
from . import layout as L
from . import names as N


def _package_of_entry(base_pkg, rel_parts, folder_logic):
    """Package of one entry, from the folders between src/ and the file.

    abapGit writes sub-packages two ways, and getting it wrong renames real packages:

      FOLDER_LOGIC=FULL     src/zqm_qcm_interface/  -> ZXX_QM_INTERFACE
      FOLDER_LOGIC=PREFIX   src/demos/              -> <parent>_DEMOS

    A folder that already looks like a package name (starts with Z/Y/$) is taken as-is
    under either logic; anything else is a suffix. Reading 'demos' as a package called
    DEMOS is how a third-party demo sub-package escapes its own exclusion rule.
    """
    if not rel_parts:
        return base_pkg
    folder = "_".join(p.upper() for p in rel_parts)
    if folder.startswith(("Z", "Y", "$")):
        return folder
    if folder_logic == "FULL" and not base_pkg:
        return folder
    return f"{base_pkg}_{folder}" if base_pkg else folder


# --- providers ------------------------------------------------------------------------
def from_tree(cfg, parse):
    """Package per object from the folder structure."""
    claims = {}          # (name, type) -> package
    stats = collections.Counter()
    for root in cfg.source_roots:
        if not root.exists():
            continue
        repo = root.parent if root.name.lower() == "src" else root
        ag = L.read_folder_logic(repo) or {}
        folder_logic = (ag.get("folder_logic") or "PREFIX").upper()
        base = (cfg.data.get("packages", {}).get("root_package")
                or L.package_name_of_dir(repo) or "")
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            parsed = parse(path.name)
            if parsed is None or path.name == "package.devc.xml":
                continue
            rel = path.parent.relative_to(root).parts
            pkg = _package_of_entry(base.upper(), rel, folder_logic)
            if not pkg:
                stats["no_package"] += 1
                continue
            claims.setdefault((parsed.object_name, parsed.object_type.upper()), pkg)
            stats["claimed"] += 1
    return claims, dict(stats)


def from_zips(cfg, parse, spec):
    """Package per object from per-package export archives."""
    path = spec.get("path", ".")
    zdir = pathlib.Path(path)
    if not zdir.is_absolute():
        zdir = cfg.root / zdir
    zips = sorted(zdir.glob("*.zip")) if zdir.is_dir() else []
    strip = spec.get("strip_prefixes", cfg.package_strip_prefixes)

    # filename -> {packages claiming it}. Keyed by BASENAME, because a flat src/ has no
    # folders to key on -- which also means a file mirrored into two exports collapses
    # here instead of being double-counted.
    by_file = collections.defaultdict(set)
    per_zip = {}
    for z in zips:
        root_pkg = L.package_of_zip(z.stem, strip)
        try:
            with zipfile.ZipFile(z) as zf:
                entries = [n for n in zf.namelist() if not n.endswith("/")]
        except (zipfile.BadZipFile, OSError):
            per_zip[root_pkg] = {"entries": 0, "kept": 0, "error": "unreadable"}
            continue
        kept = 0
        for n in entries:
            parts = n.split("/")
            base = parts[-1]
            if base in (".abapgit.xml", "package.devc.xml"):
                continue
            sub = parts[parts.index("src") + 1:-1] if "src" in parts else []
            by_file[base].add(_package_of_entry(root_pkg, sub, "PREFIX"))
            kept += 1
        per_zip[root_pkg] = {"entries": len(entries), "kept": kept}

    claims, ambiguous = {}, {}
    for fname, pkgs in sorted(by_file.items()):
        parsed = parse(fname)
        if parsed is None:
            continue
        # A parent package and its sub-package both claiming a file is not a conflict;
        # prefer the shorter (export-root) name, which is what SAP-side exports report.
        pkg = min(pkgs, key=len) if len(pkgs) > 1 else next(iter(pkgs))
        if len(pkgs) > 1 and len({p.split("_")[0] for p in pkgs}) > 1:
            ambiguous[fname] = sorted(pkgs)
        claims.setdefault((parsed.object_name, parsed.object_type.upper()), pkg)
    return claims, {"zips": len(zips), "zip_dir": str(zdir), "per_zip": per_zip,
                    "claimed_files": len(by_file), "ambiguous": len(ambiguous),
                    "ambiguous_examples": dict(list(ambiguous.items())[:5])}


def from_csv(cfg, parse, spec):
    """Package per object from an explicit list."""
    path = pathlib.Path(spec["path"])
    if not path.is_absolute():
        path = cfg.root / path
    if not path.exists():
        return {}, {"error": f"{path} not found"}
    obj_col = spec.get("object_column", "object_name")
    pkg_col = spec.get("package_column", "package")
    type_col = spec.get("type_column")
    delim = spec.get("delimiter", "\t" if path.suffix.lower() in (".tsv", ".tab")
                     else ",")
    claims, rows = {}, 0
    with path.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
        for row in csv.DictReader(fh, delimiter=delim):
            name = (row.get(obj_col) or "").strip().upper()
            pkg = (row.get(pkg_col) or "").strip().upper()
            if not name or not pkg:
                continue
            rows += 1
            otype = (row.get(type_col) or "").strip().upper() if type_col else ""
            claims.setdefault((name, otype), pkg)
    return claims, {"rows": rows, "source": str(path)}


# --- build ----------------------------------------------------------------------------
def build(cfg, verbose=True):
    parse = N.make_parser(cfg.known_types)
    providers = cfg.package_providers or [{"type": "tree"}]

    # Objects that really exist, from the scan. The map is only interesting where it
    # covers them.
    universe = {}
    sig = cfg.work("object_signals.tsv")
    if sig.exists():
        with sig.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                universe[(row["object_name"], row["object_type"])] = row["object_type"]

    obj_pkg = {}          # (name, type) -> (package, source)
    prov_stats = []
    for spec in providers:
        kind = spec.get("type")
        if kind == "tree":
            claims, st = from_tree(cfg, parse)
        elif kind == "zips":
            claims, st = from_zips(cfg, parse, spec)
        elif kind == "csv":
            claims, st = from_csv(cfg, parse, spec)
        else:
            prov_stats.append({"type": kind, "error": "unknown provider type"})
            continue
        added = outside = 0
        for key, pkg in claims.items():
            if key in obj_pkg:
                continue
            # A claim for something the scan never saw is noise, and it can be a LOT of
            # noise: one stray $TMP.zip in an export folder can claim tens of thousands
            # of objects and bury every real package in the report. The map exists to serve objects
            # that are in scope, so anything outside the scanned tree is counted and
            # dropped.
            if universe and key not in universe and key[1] != "":
                outside += 1
                continue
            # A csv provider may carry no object type: fall back to name-only matching.
            if key[1] == "":
                for (n, t) in universe:
                    if n == key[0] and (n, t) not in obj_pkg:
                        obj_pkg[(n, t)] = (pkg, kind)
                        added += 1
                continue
            obj_pkg[key] = (pkg, kind)
            added += 1
        st.update({"type": kind, "claims": len(claims), "new_assignments": added,
                   "claims_outside_scanned_tree": outside})
        prov_stats.append(st)
        if verbose:
            print(f"provider {kind:<6} claimed {len(claims):>6} -> "
                  f"{added:>6} new assignments"
                  + (f"  ({outside} claims outside the scanned tree, dropped)"
                     if outside else ""))

    # --- reconciliation against the scanned universe -----------------------------------
    covered = {k for k in obj_pkg if k in universe} if universe else set(obj_pkg)
    unmapped = sorted(k for k in universe if k not in obj_pkg)
    orphan = sorted(k for k in obj_pkg if universe and k not in universe)

    out = cfg.work("object_package_map.tsv")
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("object_name\tobject_type\tpackage\tsource\n")
        for (name, otype), (pkg, src) in sorted(obj_pkg.items()):
            fh.write(f"{name}\t{otype}\t{pkg}\t{src}\n")

    dist = collections.Counter(p for p, _s in obj_pkg.values())
    by_name = collections.defaultdict(set)
    for (name, _t), (pkg, _s) in obj_pkg.items():
        by_name[name].add(pkg)
    held = H.agreement(dict(by_name), _resolve_heldout(cfg))

    # Packages with no module mapping. This is the single most common reason a fresh
    # estate attributes badly, so it is a first-class output, not a warning buried in a
    # log: every unmapped package is a decision waiting for a human.
    unmapped_pkgs = {p: n for p, n in dist.items()
                     if p not in cfg.package_modules
                     and p not in cfg.excluded_packages}

    stats = {
        "providers": prov_stats,
        "objects_in_universe": len(universe),
        "objects_mapped": len(obj_pkg),
        "objects_mapped_in_universe": len(covered),
        "objects_unmapped": len(unmapped),
        "unmapped_examples": [f"{n}.{t}" for n, t in unmapped[:10]],
        "mapped_but_absent_from_tree": len(orphan),
        "package_count": len(dist),
        "packages": dict(sorted(dist.items())),
        "packages_without_module_mapping": dict(sorted(unmapped_pkgs.items(),
                                                       key=lambda kv: -kv[1])),
        "package_descriptions": _descriptions(cfg),
        "held_out": held,
        "coverage_pct": round(100.0 * len(covered) / len(universe), 2)
        if universe else None,
    }
    stats_path = cfg.work("package_map_stats.json")
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    if verbose:
        print(f"\ndistinct objects mapped: {len(obj_pkg)}"
              + (f"  ({stats['coverage_pct']}% of the {len(universe)} scanned)"
                 if universe else ""))
        print(f"packages: {len(dist)}")
        for pkg, n in dist.most_common(30):
            flag = "" if pkg in cfg.package_modules else \
                ("  (third-party, excluded)" if pkg in cfg.excluded_packages
                 else "  <-- NO MODULE MAPPING")
            print(f"  {pkg:<28} {n:>6}{flag}")
        if unmapped:
            print(f"\n{len(unmapped)} scanned objects have no package "
                  f"(rule R1 cannot fire for them): "
                  f"{', '.join(f'{n}.{t}' for n, t in unmapped[:5])}")
        if held:
            print(f"\nheld-out package agreement: {held['agree']}/{held['total']} = "
                  f"{held['rate']:.2f}%  ({held['unresolved']} unresolvable)")
        else:
            print("\nheld-out validation: NOT AVAILABLE (no validation.held_out.csv "
                  "configured) -- rule R1 is unvalidated in this run, and the "
                  "deliverable will say so")
        print(f"\nwrote {cfg.rel(out)}")
        print(f"wrote {cfg.rel(stats_path)}")
    return stats


def _resolve_heldout(cfg):
    spec = dict(cfg.held_out or {})
    if spec.get("csv"):
        p = pathlib.Path(spec["csv"])
        spec["csv"] = p if p.is_absolute() else cfg.root / p
    return spec


def _descriptions(cfg):
    """package -> CTEXT, the package short text abapGit keeps in package.devc.xml."""
    repos = []
    for root in cfg.source_roots:
        if root.exists():
            repo = root.parent if root.name.lower() == "src" else root
            repos.append({"src": root, "package": L.package_name_of_dir(repo),
                          "abapgit": L.read_folder_logic(repo)})
    try:
        return L.package_descriptions(repos)
    except OSError:
        return {}


def load_map(cfg):
    """object_name -> package (first wins), for the downstream steps."""
    path = cfg.work("object_package_map.tsv")
    out = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out.setdefault(row["object_name"], row["package"])
    return out
