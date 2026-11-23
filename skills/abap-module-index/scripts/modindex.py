#!/usr/bin/env python3
"""
modindex.py -- build a module index for any abapGit-serialised ABAP repository.

One row per entry-point unit (T-Code, service, enhancement, CDS view, orphan program),
with a tick per business module that has a stake in it, every tick carrying its
evidence.

    python modindex.py detect                 what layout is this repo?
    python modindex.py init                   write module-index.config.json
    python modindex.py run --to packages      scan + package map + first proposals
    python modindex.py discover --adopt       fold the proposals into the config
    python modindex.py run                    full pipeline
    python modindex.py run --from attribute   re-tune rules without re-reading src/
    python modindex.py validate               just the gates

Steps and their outputs:

    scan       object_signals.tsv, edges_raw.csv, object_files.tsv
    packages   object_package_map.tsv, package_map_stats.json
    graph      edges.csv, fanin.tsv
    units      units.tsv, unit_members.tsv, unattached.tsv, dangling_refs.tsv
    attribute  module_matrix.tsv, module_attribution.tsv, proposals.tsv
    residual   coverage_by_object.tsv, module_matrix.residual.tsv, residual.json
    discover   <prefix>-discovery.md, discovery.json, unresolved_names.tsv
    discover   discovery.json, <prefix>-discovery.md
    overrides  module_matrix.final.tsv
    render     <prefix>.xlsx / .csv / .md
    validate   <prefix>-validation.md, spotcheck_sample.csv

`scan` is the ONLY step that touches the source tree. Everything after it works from
the cached files, so re-tuning rule tables and re-rendering never re-walks a tree that
may live on a synced drive.

Consultant corrections are not part of the pipeline: they live in
overrides/module-overrides.csv, which no step ever writes.
"""

import argparse
import json
import pathlib
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from modlib import config as C            # noqa: E402
from modlib import layout as L            # noqa: E402

STEPS = [
    ("scan", "one pass over the tree: signals + all edges"),
    ("packages", "object -> home package, from whatever the repo offers"),
    ("graph", "merge, dedupe, drop self-loops, compute fan-in"),
    ("units", "enumerate roots, fold each nesting into a unit"),
    ("attribute", "run the rule ladder over every unit"),
    ("residual", "attribute the objects no unit reached; per-object coverage"),
    ("discover", "propose vocabulary; list the names that need research"),
    ("overrides", "apply consultant corrections, last"),
    ("render", "the deliverable: workbook, csv, narrative"),
    ("validate", "reconciliation, held-out and adversarial gates"),
]
STEP_NAMES = [s for s, _d in STEPS]


# --- steps ----------------------------------------------------------------------------
def step_scan(cfg, args):
    from modlib import scan
    return scan.run(cfg)


def step_packages(cfg, args):
    from modlib import packages
    return packages.build(cfg)


def step_graph(cfg, args):
    from modlib import graph
    return graph.build(cfg)


def step_units(cfg, args):
    from modlib import units
    return units.build(cfg)


def step_attribute(cfg, args):
    from modlib import attribute
    return attribute.run(cfg)


def step_residual(cfg, args):
    from modlib import residual
    return residual.run(cfg)


def step_discover(cfg, args):
    from modlib import discover, unresolved
    discover.propose(cfg)
    discover.register(cfg)
    stats = unresolved.run(cfg)
    return stats


def step_overrides(cfg, args):
    from modlib import overrides
    return overrides.apply(cfg)


def step_render(cfg, args):
    from modlib import render
    return render.run(cfg)


def step_validate(cfg, args):
    from modlib import validate
    return validate.run(cfg)


RUNNERS = {"scan": step_scan, "packages": step_packages, "graph": step_graph,
           "units": step_units, "attribute": step_attribute,
           "residual": step_residual,
           "discover": step_discover, "overrides": step_overrides,
           "render": step_render, "validate": step_validate}


# --- detect ---------------------------------------------------------------------------
def cmd_detect(args):
    knowledge = C.load_knowledge()
    known = set(knowledge["object_types"]["known"])
    root = pathlib.Path(args.root or ".").resolve()
    det = L.classify(root, known)
    zips = L.find_package_zips(root, known)
    heldout = L.find_heldout_candidates(root)
    print(L.describe(det, zips, heldout))
    if det["layout"] == "unknown":
        print("\nNo abapGit object files found. Point --root at the directory that "
              "holds the serialised objects (the one containing src/, or the parent of "
              "the per-package folders).")
        return 1
    if det["layout"] == "flat-export" and not zips:
        print("\nNOTE: a flat export carries NO package information -- abapGit strips "
              "<DEVCLASS> from every object file. Rule R1 (home package), the only "
              "authoritative signal, cannot fire. Supply the per-package export zips, "
              "or an object->package CSV, or accept name-based attribution only.")
    return 0


# --- init -----------------------------------------------------------------------------
def _proposed_config(root, det, zips, heldout, knowledge):
    src_roots, providers = [], []
    for r in det["repos"]:
        src_roots.append(_rel(root, r["src"]))
    if det["layout"] in ("package-per-folder", "abapgit-repo", "multi-repo"):
        providers.append({"type": "tree"})
    if zips:
        zdir = max(zips, key=lambda d: sum(i["objects"] for i in zips[d]))
        providers.append({"type": "zips", "path": _rel(root, zdir),
                          "strip_prefixes": L.guess_strip_prefixes(zips[zdir])})
    if not providers:
        providers.append({"type": "tree"})

    packages = {}
    for r in det["repos"]:
        if r["package"]:
            packages[r["package"]] = []
    for zdir, infos in zips.items():
        strip = L.guess_strip_prefixes(infos)
        for i in infos:
            packages.setdefault(L.package_of_zip(i["zip"].stem, strip), [])

    cfg = {
        "$schema": C.SCHEMA,
        "project": root.name,
        "paths": {
            "source_roots": src_roots or ["src"],
            "work_dir": "utilities/module-index",
            "out_dir": "utilities/module-index",
            "out_prefix": "appendix-module-index",
        },
        "modules": {
            # Narrow this to the modules this customer actually runs. The vocabulary is
            # OPEN: anything the rules name beyond this list is reported as a proposal
            # with its evidence, never dropped.
            "core": knowledge["modules"]["core"],
            "buckets": {},
            "open": True,
            "not_modules": {},
        },
        "packages": {
            "providers": providers,
            "map": dict(sorted(packages.items())),
            "excluded": [],
        },
        "naming": {"families": []},
        "text": {"keywords": {}},
        "tuning": {},
        "validation": {"thresholds": {}, "assertions": []},
        "seed": 20260101,
    }
    if heldout:
        h = heldout[0]
        cfg["validation"]["held_out"] = {
            "csv": _rel(root, h["csv"]),
            "object_column": h["object_column"],
            "package_column": h["package_column"],
            "delimiter": h["delimiter"],
        }
    return cfg


def _rel(root, path):
    try:
        return pathlib.Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def cmd_init(args):
    knowledge = C.load_knowledge()
    known = set(knowledge["object_types"]["known"])
    root = pathlib.Path(args.root or ".").resolve()
    det = L.classify(root, known)
    if det["layout"] == "unknown":
        print("No abapGit object files found under "
              f"{root} -- nothing to configure. Try --root.")
        return 1
    zips = L.find_package_zips(root, known)
    heldout = L.find_heldout_candidates(root)
    print(L.describe(det, zips, heldout))

    data = _proposed_config(root, det, zips, heldout, knowledge)
    out = pathlib.Path(args.out) if args.out else root / C.CONFIG_NAME
    if out.exists() and not args.force:
        print(f"\n{out} already exists -- refusing to overwrite. Use --force (a "
              f"timestamped backup is kept) or edit it by hand.")
        return 1
    if out.exists():
        backup = out.with_suffix(f".json.bak{int(time.time())}")
        shutil.copyfile(out, backup)
        print(f"backed up existing config to {backup.name}")
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"\nwrote {out}")
    print(f"  source roots: {', '.join(data['paths']['source_roots'])}")
    print(f"  package providers: "
          f"{', '.join(p['type'] for p in data['packages']['providers'])}")
    print(f"  packages awaiting a module mapping: {len(data['packages']['map'])}")
    print("\nNext:")
    print("  1. python modindex.py run --to packages     (scan + map + proposals)")
    print("  2. python modindex.py discover --adopt      (fold proposals into config)")
    print("  3. review module-index.config.json by hand  (the module list is yours to "
          "decide, not the tool's)")
    print("  4. python modindex.py run")
    return 0


# --- config check ---------------------------------------------------------------------
def cmd_check(args):
    path = pathlib.Path(args.config) if args.config else \
        C.find_config(args.root or ".")
    if not path:
        print(f"no {C.CONFIG_NAME} found -- run `init`")
        return 1
    knowledge = C.load_knowledge()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    problems = C.validate_data(data, knowledge)
    cfg = C.load(path)
    print(json.dumps(cfg.summary(), indent=2))
    if problems:
        print("\nconfig notes:")
        for p in problems:
            print(f"  - {p}")
    hard = [p for p in problems if not p.startswith("NOTE")]
    return 1 if hard else 0


# --- discover -------------------------------------------------------------------------
def cmd_discover(args):
    from modlib import discover
    cfg = C.load(args.config, args.root)
    out = discover.propose(cfg)
    if not args.propose_only:
        discover.register(cfg)
    if not args.adopt:
        return 0

    # Fold the proposals into the config: package -> module mappings whose suggestion
    # is already in the vocabulary are written directly; everything else is parked
    # under an ignored "_" key so it stays visible without silently taking effect.
    path = cfg.path
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    pmap = data.setdefault("packages", {}).setdefault("map", {})
    adopted, parked = [], []
    for p in out["packages"]:
        pkg = p["package"]
        if pmap.get(pkg):
            continue
        if p.get("confident"):
            pmap[pkg] = [p["confident"]]
            adopted.append(f"{pkg} -> {p['confident']}   "
                           f"({'; '.join(p['evidence'][p['confident']])})")
        else:
            parked.append({"package": pkg, "objects": p["objects"],
                           "description": p["description"],
                           "suggested": p["suggested"],
                           "evidence": p["evidence"]})
    data["_packages_needing_a_decision"] = parked
    data["_modules_with_evidence_but_no_column"] = [
        {"module": m["module"], "objects": m["objects"],
         "tables": list(m["tables"])[:6]}
        for m in out["modules_with_evidence_but_no_column"]]
    data["_naming_segments_needing_a_decision"] = [
        {"segment": s["segment"], "objects": s["objects"],
         "examples": s["examples"][:3]} for s in out["unknown_segments"][:20]]

    backup = path.with_suffix(f".json.bak{int(time.time())}")
    shutil.copyfile(path, backup)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"\nbacked up {path.name} -> {backup.name}")
    print(f"adopted {len(adopted)} package mappings:")
    for a in adopted[:20]:
        print(f"  {a}")
    if parked:
        print(f"\n{len(parked)} packages could not be mapped automatically. They are "
              "parked under \"_packages_needing_a_decision\" in the config -- that key "
              "is ignored by the build, so nothing takes effect until you move the "
              "entries into packages.map yourself.")
    print(f"\nreview {path.name}, then: python modindex.py run --from attribute")
    return 0


# --- overrides ------------------------------------------------------------------------
def cmd_overrides(args):
    from modlib import overrides
    cfg = C.load(args.config, args.root)
    if args.ingest:
        if not args.reviewer:
            print("--ingest requires --reviewer")
            return 1
        overrides.ingest(cfg, pathlib.Path(args.ingest), args.reviewer)
        return 0
    overrides.apply(cfg)
    return 0


# --- run ------------------------------------------------------------------------------
def cmd_run(args):
    cfg = C.load(args.config, args.root)
    start = STEP_NAMES.index(args.start) if args.start else 0
    end = STEP_NAMES.index(args.end) if args.end else len(STEP_NAMES) - 1
    if args.only:
        start = end = STEP_NAMES.index(args.only)
    if start > end:
        print("--from is after --to")
        return 1
    order = STEP_NAMES[start:end + 1]

    if args.dry_run:
        print(json.dumps(cfg.summary(), indent=2))
        print()
        for name, desc in STEPS:
            mark = ">" if name in order else " "
            print(f" {mark} {name:<11} {desc}")
        return 0

    from modlib import stamps
    stale = stamps.stale_before(cfg, order[0])
    if stale and not args.force:
        print(f"\nSTALE INPUTS: the config sections that {', '.join(stale)} depend on "
              f"have changed since {'they were' if len(stale) > 1 else 'it was'} last "
              f"run, so starting at `{order[0]}` would build on out-of-date files.\n"
              f"  Re-run from the earliest affected step:  "
              f"python modindex.py run --from {stale[0]}\n"
              f"  Or override deliberately:                --force")
        return 2

    print(json.dumps(cfg.summary(), indent=2))
    t0 = time.time()
    for name in order:
        desc = dict(STEPS)[name]
        print(f"\n{'=' * 78}\n[{name}] {desc}\n{'=' * 78}")
        t = time.time()
        try:
            RUNNERS[name](cfg, args)
            stamps.record(cfg, name)
        except FileNotFoundError as exc:
            print(f"\nSTEP {name} FAILED: {exc}")
            return 2
        except AssertionError as exc:
            print(f"\nSTEP {name} FAILED: {exc}")
            return 2
        print(f"-- step {name} ok in {time.time() - t:.1f}s")
    print(f"\n{'=' * 78}\npipeline complete in {time.time() - t0:.1f}s")

    if "validate" in order:
        from modlib import validate
        # validate already printed its verdicts; re-read them cheaply for the exit code
        rep = cfg.out("-validation.md")
        if rep.exists() and "**FAIL**" in rep.read_text(encoding="utf-8"):
            print("\nVALIDATION FAILED -- do not ship this workbook until the failing "
                  "gates are fixed.")
            return 1
    return 0


# --- main -----------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Module index for abapGit-serialised ABAP repositories.")
    ap.add_argument("--root", help="repository root (default: cwd)")
    ap.add_argument("--config", help=f"path to {C.CONFIG_NAME}")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("detect", help="report the repository layout and package sources")

    p = sub.add_parser("init", help="write a config from what is in the tree")
    p.add_argument("--out")
    p.add_argument("--force", action="store_true")

    sub.add_parser("check", help="validate the config and print the resolved settings")

    p = sub.add_parser("discover", help="propose the vocabulary; register open items")
    p.add_argument("--adopt", action="store_true",
                   help="write unambiguous proposals into the config")
    p.add_argument("--propose-only", action="store_true")

    p = sub.add_parser("overrides", help="apply or ingest consultant corrections")
    p.add_argument("--ingest", metavar="XLSX")
    p.add_argument("--reviewer", default="")

    p = sub.add_parser("run", help="run the pipeline")
    p.add_argument("--from", dest="start", choices=STEP_NAMES)
    p.add_argument("--to", dest="end", choices=STEP_NAMES)
    p.add_argument("--only", choices=STEP_NAMES)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="run even when earlier steps' inputs have changed")

    # Each step is also callable on its own. `discover` and `overrides` already have
    # richer parsers above, so they are not re-registered.
    for name, desc in STEPS:
        if name in sub.choices:
            continue
        sub.add_parser(name, help=desc)

    args = ap.parse_args(argv)
    cmd = args.cmd or "run"
    try:
        if cmd == "detect":
            return cmd_detect(args)
        if cmd == "init":
            return cmd_init(args)
        if cmd == "check":
            return cmd_check(args)
        if cmd == "discover":
            return cmd_discover(args)
        if cmd == "overrides":
            return cmd_overrides(args)
        if cmd == "run":
            args.only = getattr(args, "only", None)
            args.start = getattr(args, "start", None)
            args.end = getattr(args, "end", None)
            args.dry_run = getattr(args, "dry_run", False)
            args.force = getattr(args, "force", False)
            return cmd_run(args)
        if cmd in RUNNERS:
            cfg = C.load(args.config, args.root)
            from modlib import stamps
            stale = stamps.stale_before(cfg, cmd)
            if stale:
                print(f"WARNING: {', '.join(stale)} ran with different config inputs "
                      f"than the current file -- this step is building on stale "
                      f"artefacts. Consider: python modindex.py run --from "
                      f"{stale[0]}\n")
            RUNNERS[cmd](cfg, args)
            stamps.record(cfg, cmd)
            return 0
        ap.print_help()
        return 1
    except C.ConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
