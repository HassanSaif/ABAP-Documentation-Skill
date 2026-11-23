#!/usr/bin/env python3
"""
measure_signals.py -- how credible is each attribution signal in THIS estate?

The rule ladder assigns an authority to every signal, and those authorities were set
from measurements on real estates rather than from intuition. This script re-runs those
measurements on the estate in front of you, so the ranking can be checked rather than
believed.

    python measure_signals.py --config module-index.config.json --root .

Three measurements, in decreasing order of how much they prove:

  1. AGAINST HELD-OUT TRUTH  (needs validation.held_out configured)
     For objects whose module is known independently -- an SAP-side export whose
     `package` column is never an attribution input -- how often is each signal right?
     This is the only measurement that can rank signals against each other.

  2. NAME vs CONTENT AGREEMENT  (always available)
     Name evidence reads what an object is CALLED; content evidence reads which
     modules' standard tables it TOUCHES. They are independent, so where both fire
     they should mostly agree. Disagreements are a triage list: either the object
     legitimately serves another module's data, or a naming rule is wrong.

  3. COVERAGE  (always available)
     A signal that is 100% accurate on 1% of the estate cannot carry the attribution.
     Accuracy without coverage is a footnote, not a rule.

The ranking it is expected to reproduce, from reference estates with held-out truth:

    writing a module's tables         most accurate of all, but fires rarely
    naming conventions                close behind, and fires widely
    reading a module's tables         clearly weaker
    calling a module's change BAPIs   clearly weaker

Run it to get the actual numbers for YOUR estate; never quote another estate's. That
ranking is why table WRITES are AUTHORITATIVE in the ladder while reads and API
calls are INFERRED: every module reads and calls every other module all day, but
writing straight into another module's tables is rare and deliberate.
"""

import argparse
import collections
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
csv.field_size_limit(10_000_000)

from modlib import config as C      # noqa: E402
from modlib import heldout as H     # noqa: E402
from modlib import rules as R       # noqa: E402


def read(path, delim="\t"):
    if not path.exists():
        return []
    enc = "utf-8-sig" if delim == "," else "utf-8"
    with path.open(encoding=enc, newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delim))


def modules_from(counter, min_hits=2):
    """The modules a set of table hits actually points at, or nothing."""
    if not counter:
        return set()
    top = counter.most_common(1)[0][1]
    return {m for m, n in counter.items() if n >= max(min_hits, top * 0.5)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--root")
    a = ap.parse_args()
    cfg = C.load(a.config, a.root)
    work = cfg.work_dir

    signals = read(work / "object_signals.tsv")
    matrix = read(work / "module_matrix.final.tsv") or read(work / "module_matrix.tsv")
    members = read(work / "unit_members.tsv")
    if not signals:
        sys.exit(f"no scan output in {cfg.rel(work)} -- run the pipeline first")

    reads = {r["object_name"]: [t for t in (r.get("std_tables") or "").split("|") if t]
             for r in signals}
    writes = {r["object_name"]: [t for t in
                                 (r.get("std_tables_written") or "").split("|") if t]
              for r in signals}
    calls = {r["object_name"]: [c for c in (r.get("std_calls") or "").split("|") if c]
             for r in signals}

    def tab_modules(names, src):
        c = collections.Counter()
        for n in names:
            for t in src.get(n, []):
                m = cfg.table_to_module.get(t)
                if m:
                    c[m] += 1
        return c

    def call_modules(names):
        c = collections.Counter()
        for n in names:
            for call in calls.get(n, []):
                m = R.std_call_module(cfg, call)
                if m:
                    c[m] += 1
        return c

    def name_modules(name):
        return ({m for m, _ in R.name_tokens(cfg, name)}
                | {m for m, _ in R.family_hits(cfg, name)}
                | {m for m, _ in R.wrapper_hits(cfg, name)})

    print("=" * 76)
    print(f"SIGNAL CREDIBILITY -- {cfg.project}")
    print("=" * 76)

    # --- 1. held-out ------------------------------------------------------------------
    spec = dict(cfg.held_out or {})
    if spec.get("csv"):
        p = pathlib.Path(spec["csv"])
        spec["csv"] = p if p.is_absolute() else cfg.root / p
    ref = H.load_reference(spec)
    truth = {}
    for obj, pkgs in ref.items():
        exp = set()
        for pk in pkgs:
            exp |= set(cfg.package_modules.get(pk, []))
        if exp:
            truth[obj] = exp

    print("\n1. AGAINST HELD-OUT TRUTH")
    if not truth:
        print("   not available -- configure validation.held_out with an SAP-side")
        print("   export carrying object and package columns. Without it, no signal")
        print("   can be ranked against another on this estate.")
    else:
        print(f"   {len(truth)} objects with an independently known module\n")
        print(f"   {'signal':<32}{'fired on':>10}{'correct':>10}{'accuracy':>11}")
        rows = [
            ("writes a module's tables",
             lambda o: modules_from(tab_modules([o], writes), 1)),
            ("naming conventions", name_modules),
            ("reads a module's tables",
             lambda o: modules_from(tab_modules([o], reads))),
            ("calls a module's std APIs",
             lambda o: modules_from(call_modules([o]))),
        ]
        for label, fn in rows:
            hit = miss = 0
            for obj, exp in truth.items():
                got = fn(obj)
                if not got:
                    continue
                if got & exp:
                    hit += 1
                else:
                    miss += 1
            tot = hit + miss
            acc = 100 * hit / tot if tot else 0
            print(f"   {label:<32}{tot:>10}{hit:>10}{acc:>10.1f}%")

    # --- 2. name vs content -----------------------------------------------------------
    print("\n2. NAME vs CONTENT AGREEMENT")
    by_unit = collections.defaultdict(list)
    for m in members:
        by_unit[m["unit_id"]].append(m["member"])
    name_rx = re.compile(r"(?:^|; )(?:name|member-name|family|std-wrapper|tcode->prog):")
    agree = disagree = 0
    conflicts = []
    for r in matrix:
        if not name_rx.search(r.get("evidence") or ""):
            continue
        names = [r["root_object"]] + by_unit.get(r["unit_id"], [])
        counted = collections.Counter(
            {m: n for m, n in tab_modules(names, reads).items() if cfg.in_vocab(m)})
        content = modules_from(counted)
        if not content:
            continue
        ticked = {m for m in cfg.all_modules if r.get(m) == "X"}
        if content & ticked:
            agree += 1
        else:
            disagree += 1
            conflicts.append((r["root_object"], sorted(content), sorted(ticked)))
    both = agree + disagree
    if both:
        print(f"   both signals fire on {both} units: "
              f"{agree} agree ({100 * agree / both:.1f}%), {disagree} conflict")
        print(f"   gate threshold: {cfg.thresholds['min_content_name_agreement_pct']}%")
        if conflicts:
            print("\n   conflicts (tables suggest -> ticked):")
            for obj, content, ticked in conflicts[:20]:
                print(f"     {obj:<34} {', '.join(content):<14} -> "
                      f"{', '.join(ticked) or '-'}")
            if len(conflicts) > 20:
                print(f"     ... and {len(conflicts) - 20} more")
    else:
        print("   no unit has both signals -- nothing to cross-check")

    # --- 3. coverage ------------------------------------------------------------------
    print("\n3. COVERAGE ACROSS THE ESTATE")
    n_units = len(matrix) or 1
    def unit_count(fn):
        c = 0
        for r in matrix:
            names = [r["root_object"]] + by_unit.get(r["unit_id"], [])
            if fn(names):
                c += 1
        return c
    w = unit_count(lambda ns: modules_from(tab_modules(ns, writes), 1))
    rd = unit_count(lambda ns: modules_from(tab_modules(ns, reads)))
    cl = unit_count(lambda ns: modules_from(call_modules(ns)))
    nm = unit_count(lambda ns: name_modules(ns[0]))
    for label, c in (("writes a module's tables", w), ("naming conventions", nm),
                     ("reads a module's tables", rd), ("calls a module's std APIs", cl)):
        print(f"   {label:<32}{c:>7} units  ({100 * c / n_units:5.1f}%)")
    print("\n   A signal that is highly accurate but fires on 1% of units cannot carry")
    print("   the attribution -- it raises confidence where it fires and validates the")
    print("   rules everywhere else.")


if __name__ == "__main__":
    main()
