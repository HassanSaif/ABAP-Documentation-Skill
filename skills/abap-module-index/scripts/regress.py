#!/usr/bin/env python3
"""
regress.py -- run the pipeline over several known estates and compare the gates.

Every rule in this skill was added or rejected on measured evidence, and the measuring
kept catching the same class of mistake: a change that clearly improves one estate while
quietly smearing another. Three kinds of mistake this has caught, none of them
visible on the estate the change was written for:

  * A rule widened from "the module with the most tables" to "every module with 5+
    tables" -- its accuracy had been measured on the top module only. Fine on one
    estate; on another it pushed many units onto four core modules at once.
  * Marking widely-read CUSTOMIZING tables (sales org, transportation) as discriminating
    fixed one report and tipped many others, each gaining a spurious tick.
  * Promoting a field-type rule (R18) to STRONG rescued the DDIC leaves it was written
    for and, elsewhere, made a production-cost report an MM owner on one field type.

So: two estates, one command, before shipping a rule change.

Usage
    python regress.py --estate <root>=<config> [--estate <root>=<config> ...]
    python regress.py --estate . = utilities/module-index/module-index.config.json \\
                      --baseline regression-baseline.json
    python regress.py ... --update-baseline

Keep the baseline file OUTSIDE this skill. It records absolute repository paths, and
the skill is shared across customers -- a baseline committed here would carry one
customer's directory names into everybody else's copy.

Without a baseline it prints each estate's gate counts and fails on any FAIL.
With one it also fails on any gate whose verdict CHANGED, which is the point: a rule
change should move numbers you can name, not numbers you did not know about.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
GATE = re.compile(r"^\s*\[(PASS|WARN|FAIL)\]\s+(.*?):\s*(.*)$")
SUMMARY = re.compile(r"(\d+)/(\d+) checks passed, (\d+) warned, (\d+) failed")


def run_estate(root, config, from_step=None):
    # cwd=root, because modindex resolves --config relative to the working directory,
    # not to --root. Passing an absolute root and a repo-relative config from somewhere
    # else silently looks for the config beside the WRONG repo.
    cmd = [sys.executable, str(HERE / "modindex.py"), "--root", ".",
           "--config", config, "run"]
    if from_step:
        cmd += ["--from", from_step]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=root,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    gates, summary = {}, None
    for line in out.splitlines():
        m = GATE.match(line)
        if m:
            gates[m.group(2).strip()] = {"verdict": m.group(1),
                                         "detail": m.group(3).strip()}
        m = SUMMARY.search(line)
        if m:
            summary = {"passed": int(m.group(1)), "total": int(m.group(2)),
                       "warned": int(m.group(3)), "failed": int(m.group(4))}
    return {"gates": gates, "summary": summary, "returncode": p.returncode,
            "output": out}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--estate", action="append", required=True, metavar="ROOT=CONFIG",
                    help="repeatable; ROOT is the repo root, CONFIG the path to its "
                         "module-index.config.json (relative to ROOT)")
    ap.add_argument("--from", dest="from_step", default=None,
                    help="restart each estate from this step (e.g. attribute) instead "
                         "of rescanning; the staleness gate still applies")
    ap.add_argument("--baseline", default=None,
                    help="JSON file of expected gate verdicts")
    ap.add_argument("--update-baseline", action="store_true",
                    help="write the current verdicts to --baseline and exit 0")
    args = ap.parse_args()

    results, failed = {}, False
    for spec in args.estate:
        if "=" not in spec:
            ap.error(f"--estate needs ROOT=CONFIG, got {spec!r}")
        root, config = spec.split("=", 1)
        root, config = root.strip(), config.strip()
        print(f"\n{'=' * 78}\n{root}\n{'=' * 78}")
        r = run_estate(root, config, args.from_step)
        results[root] = {"gates": r["gates"], "summary": r["summary"]}
        if r["summary"] is None:
            print("  NO VALIDATION OUTPUT -- the run did not reach the validate step")
            print("\n".join(r["output"].splitlines()[-25:]))
            failed = True
            continue
        for name, g in r["gates"].items():
            print(f"  [{g['verdict']:<4}] {name}: {g['detail']}")
        s = r["summary"]
        print(f"  -> {s['passed']}/{s['total']} passed, {s['warned']} warned, "
              f"{s['failed']} failed")
        if s["failed"]:
            failed = True

    if args.baseline and args.update_baseline:
        if failed:
            print("\nrefusing to write a baseline from a run that failed")
            return 1
        pathlib.Path(args.baseline).write_text(
            json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nwrote baseline {args.baseline}")
        return 0

    if args.baseline and pathlib.Path(args.baseline).exists():
        base = json.loads(pathlib.Path(args.baseline).read_text(encoding="utf-8"))
        print(f"\n{'=' * 78}\nagainst baseline {args.baseline}\n{'=' * 78}")
        drift = 0
        for root, cur in results.items():
            old = base.get(root, {}).get("gates", {})
            for name, g in cur["gates"].items():
                prev = old.get(name)
                if prev is None:
                    print(f"  NEW   {root}: {name} -> {g['verdict']}")
                    drift += 1
                elif prev["verdict"] != g["verdict"]:
                    print(f"  MOVED {root}: {name}: "
                          f"{prev['verdict']} -> {g['verdict']}  ({g['detail']})")
                    drift += 1
            for name in old:
                if name not in cur["gates"]:
                    print(f"  GONE  {root}: {name}")
                    drift += 1
        if drift:
            print(f"\n{drift} gate verdicts moved. If that is the change you meant, "
                  f"re-run with --update-baseline.")
            failed = True
        else:
            print("  no gate verdict moved")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
