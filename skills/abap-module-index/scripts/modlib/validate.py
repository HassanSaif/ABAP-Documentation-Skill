"""
validate.py -- prove the attribution, or fail loudly.

Four kinds of check, and the difference between them matters:

  reconciliation  nothing may vanish. The three populations must account for every
                  object that was scanned.
  held-out        a source SAP-side column that is never an input to the attribution,
                  used as independent truth for rule R1. When there is none, this
                  reports NOT VALIDATED -- never a pass. An unvalidated run is a
                  legitimate state; a run that claims validation it does not have is
                  not.
  adversarial     cheap assertions that catch systemic error. Site-specific ones live
                  in the config, because the useful ones are always local knowledge
                  ("every handheld transaction must tick warehousing").
  open-vocabulary evidence for a module with no tick column. AUTHORITATIVE evidence for
                  an area the config never names is a FAILURE of the vocabulary, not a
                  curiosity -- the estate has a module you have not modelled.

Verdicts are PASS / WARN / FAIL. Only FAIL sets a non-zero exit code, and a FAIL means
do not ship this workbook.

Also emits a reproducible stratified sample for manual review, because no amount of
internal consistency substitutes for a consultant reading 50 rows.
"""

import collections
import csv
import json
import random
import re

from . import heldout as H

csv.field_size_limit(10_000_000)


def _read(path, delim="\t"):
    if not path.exists():
        return []
    enc = "utf-8-sig" if delim == "," else "utf-8"
    with path.open(encoding=enc, newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delim))


_RULED_OUT_RX = re.compile(r"named ([A-Z_0-9,]+) \(ruled out")


def run(cfg, verbose=True):
    matrix = _read(cfg.work("module_matrix.final.tsv")) \
        or _read(cfg.work("module_matrix.tsv"))
    members = _read(cfg.work("unit_members.tsv"))
    unattached = _read(cfg.work("unattached.tsv"))
    pkg_rows = _read(cfg.work("object_package_map.tsv"))
    signals = _read(cfg.work("object_signals.tsv"))
    proposals = _read(cfg.work("proposals.tsv"))
    stats_path = cfg.work("package_map_stats.json")
    pkg_stats = json.loads(stats_path.read_text(encoding="utf-8")) \
        if stats_path.exists() else {}

    if not matrix:
        raise FileNotFoundError("no module matrix -- run `attribute` first")

    packages = {r["object_name"]: r["package"] for r in pkg_rows}
    pkg_sets = H.packages_by_name(pkg_rows)
    n = len(matrix)
    T = cfg.thresholds
    results = []

    def check(name, verdict, detail):
        results.append((name, verdict, detail))
        if verbose:
            print(f"  [{verdict:<4}] {name}: {detail}")

    def gate(name, ok, detail, on_fail="FAIL"):
        check(name, "PASS" if ok else on_fail, detail)

    if verbose:
        print("reconciliation")
    roots = {r["root_object"] for r in matrix}
    folded = {m["member"] for m in members}
    universe = {r["object_name"] for r in signals}
    covered = len(roots | (folded & universe)) + len(unattached)
    gate("roots + members + unattached == all objects", covered == len(universe),
         f"{covered} covered of {len(universe)} scanned")

    if verbose:
        print("\nheld-out validation (rule R1)")
    spec = dict(cfg.held_out or {})
    if spec.get("csv"):
        import pathlib
        p = pathlib.Path(spec["csv"])
        spec["csv"] = p if p.is_absolute() else cfg.root / p
    ref = H.load_reference(spec)
    ha = H.agreement(pkg_sets, spec)
    misses = []
    if ha is None:
        check("package map agrees with a held-out source", "WARN",
              "NOT VALIDATED -- no validation.held_out.csv configured. Any SAP-side "
              "export with object_name + package columns closes this gap.")
        mrate = None
    else:
        gate("package map agrees with a held-out source",
             ha["rate"] >= T["min_heldout_pkg_pct"],
             f"{ha['agree']}/{ha['total']} = {ha['rate']:.2f}%  "
             f"({ha['unresolved']} unresolvable)")
        # Module-level: is the module implied by the held-out package actually ticked?
        ticks = {r["root_object"]: {m for m in cfg.all_modules if r.get(m) == "X"}
                 for r in matrix}
        unit_of = {}
        for m in members:
            unit_of.setdefault(m["member"], m["root_object"])
        hit = miss = na = 0
        for obj, pkgs in ref.items():
            expected = set()
            for p in pkgs:
                expected |= set(cfg.package_modules.get(p, []))
            expected &= set(cfg.all_modules)
            if not expected:
                na += 1
                continue
            got = ticks.get(obj) or ticks.get(unit_of.get(obj, ""), set())
            if not got:
                na += 1
            elif expected & got:
                hit += 1
            else:
                miss += 1
                if len(misses) < 12:
                    misses.append((obj, sorted(expected), sorted(got)))
        mtotal = hit + miss
        mrate = 100.0 * hit / mtotal if mtotal else 0.0
        gate("held-out-implied module is ticked", mrate >= T["min_heldout_module_pct"],
             f"HIT {hit}, MISS {miss} = {mrate:.2f}%  ({na} not in any unit)")

    if verbose:
        print("\ncoverage")
    ticked = sum(1 for r in matrix if r.get("module_count") not in ("", "0"))
    multi = sum(1 for r in matrix if int(r.get("module_count") or 0) >= 2)
    high = sum(1 for r in matrix if r.get("confidence") == "HIGH")
    gate(f"units with >= 1 tick >= {T['min_ticked_pct']}%",
         100 * ticked / n >= T["min_ticked_pct"],
         f"{ticked}/{n} = {100 * ticked / n:.1f}%")
    gate(f"UNCLASSIFIED <= {T['max_unclassified_pct']}%",
         100 * (n - ticked) / n <= T["max_unclassified_pct"],
         f"{n - ticked} = {100 * (n - ticked) / n:.1f}%")
    band = T["multi_module_band"]
    # Kept as a loose sanity bound only. As edge extraction improves, objects that
    # stood as their own single-tick rows get correctly folded into units, so the
    # DENOMINATOR shrinks while the multi-module count falls -- the ratio can rise on
    # better attribution, not worse. The real over-attribution test is the breadth
    # distribution below.
    gate(f"multi-module within {band[0]:.0f}-{band[1]:.0f}%",
         band[0] <= 100 * multi / n <= band[1],
         f"{multi} = {100 * multi / n:.1f}%", on_fail="WARN")
    breadth = collections.Counter(sum(1 for m in cfg.core if r.get(m) == "X")
                                  for r in matrix)
    wide = sum(c for k, c in breadth.items() if k >= T["max_core_breadth"])
    gate(f"no unit ticks {T['max_core_breadth']}+ core modules", wide == 0,
         f"{wide} units; distribution "
         + ", ".join(f"{k}:{breadth[k]}" for k in sorted(breadth)))
    gate("majority of units have exactly 1 core module",
         100 * breadth[1] / n >= T["min_single_core_pct"],
         f"{breadth[1]} = {100 * breadth[1] / n:.1f}%")
    gate(f"confidence HIGH >= {T['min_high_confidence_pct']}%",
         100 * high / n >= T["min_high_confidence_pct"],
         f"{high} = {100 * high / n:.1f}%")

    # --- content vs name cross-check ---------------------------------------------------
    # The one check in this file that validates the RULES rather than the output. Name
    # evidence and content evidence are independent: the first reads what an object is
    # called, the second what it actually touches. Where both fire they should mostly
    # agree, and the disagreements are the best triage list in the whole build -- this
    # is what caught a master-data family ticking MM on the asset master and the chart
    # of accounts, both of which are FI.
    #
    # Healthy estates agree well above the configured floor; a low figure means a
    # naming rule has drifted from what the code does.
    if verbose:
        print("\ncontent vs name cross-check")
    tables_of = {r["object_name"]: [t for t in (r.get("std_tables") or "").split("|")
                                    if t] for r in signals}
    by_unit = collections.defaultdict(list)
    for m in members:
        by_unit[m["unit_id"]].append(m["member"])
    name_rx = re.compile(r"(?:^|; )(?:name|member-name|family|std-wrapper|tcode->prog):")
    agree = disagree = 0
    conflicts = []
    for r in matrix:
        if not name_rx.search(r.get("evidence") or ""):
            continue
        ts = set(tables_of.get(r["root_object"], []))
        for mem in by_unit.get(r["unit_id"], []):
            ts.update(tables_of.get(mem, []))
        # Only modules that HAVE a tick column can be agreed with. Content pointing at
        # a module the site ruled out (no Warehouse Management here, so LQUA reads mean
        # nothing) is a recorded decision, not a disagreement -- counting it as one
        # would make the gate unpassable for any estate that narrows its vocabulary.
        counted = collections.Counter(cfg.table_to_module[t] for t in ts
                                      if t in cfg.table_to_module
                                      and cfg.in_vocab(cfg.table_to_module[t]))
        if not counted:
            continue
        top = counted.most_common(1)[0][1]
        content = {m for m, n in counted.items() if n >= max(2, top * 0.5)}
        if not content:
            # A single hit on a single table is not an opinion about ownership. Scoring
            # these as disagreements makes a cross-check gate read far below the real
            # agreement -- silence has to count as silence.
            continue
        ticked = {m for m in cfg.all_modules if r.get(m) == "X"}
        if content & ticked:
            agree += 1
        else:
            disagree += 1
            if len(conflicts) < 15:
                conflicts.append((r["root_object"], sorted(content), sorted(ticked)))
    both = agree + disagree
    rate = 100.0 * agree / both if both else 100.0
    gate("content and name evidence agree where both fire",
         rate >= T["min_content_name_agreement_pct"],
         f"{agree}/{both} = {rate:.1f}%"
         + (f"; {disagree} conflicts to triage" if disagree else ""))

    if verbose:
        print("\nopen vocabulary")
    prop_by_mod = collections.defaultdict(list)
    for p in proposals:
        prop_by_mod[p["proposed_module"]].append(p)
    authoritative = {m: rs for m, rs in prop_by_mod.items()
                     if any(r["authority"] == "AUTHORITATIVE" for r in rs)}
    if not prop_by_mod:
        check("every module the rules named has a tick column", "PASS",
              "no out-of-vocabulary evidence")
    elif authoritative:
        check("every module the rules named has a tick column", "FAIL",
              "AUTHORITATIVE evidence for " + ", ".join(
                  f"{m} ({len(rs)} units)" for m, rs in sorted(authoritative.items()))
              + " -- the estate has a module this config does not model. Adopt it in "
                "modules.core/buckets, or rule it out in modules.not_modules.")
    else:
        check("every module the rules named has a tick column", "WARN",
              ", ".join(f"{m} ({len(rs)} units)"
                        for m, rs in sorted(prop_by_mod.items(),
                                            key=lambda kv: -len(kv[1])))
              + " -- weaker evidence only; see the discovery report")

    # A module in not_modules is "known and deliberately rejected", so it never reaches
    # the proposal register above -- the open-vocabulary gate cannot see it. This is the
    # other half of that gate: the rules are still naming it, and the question is
    # whether the rejection is costing coverage or merely redirecting it.
    ruled_out = cfg.not_modules
    if ruled_out:
        named, silenced = collections.Counter(), collections.defaultdict(list)
        for row in matrix:
            mods = set()
            for grp in _RULED_OUT_RX.findall(row.get("notes") or ""):
                mods |= {m for m in grp.split(",") if m}
            for m in mods:
                named[m] += 1
                if not any((row.get(c) or "").strip() for c in cfg.all_modules):
                    silenced[m].append(row["root_object"])
        summary = ", ".join(f"{m} on {named[m]}" for m in sorted(named)) or "none named"
        if silenced:
            worst = sorted(silenced.items(), key=lambda kv: -len(kv[1]))
            check("a ruled-out module never silences a unit", "FAIL",
                  "; ".join(f"{m}: {len(v)} unit{'s' if len(v) != 1 else ''} with NO "
                            f"tick at all ({', '.join(v[:3])}"
                            f"{', ...' if len(v) > 3 else ''})" for m, v in worst)
                  + f" -- the rules identified these and the decision discarded the "
                    f"answer. Either the reason in modules.not_modules is stale and the "
                    f"module belongs in modules.core, or these units need a real "
                    f"second signal. Named on: {summary}")
        else:
            check("a ruled-out module never silences a unit", "PASS",
                  f"{summary} -- every one of those units carries another module, "
                  f"which is what the recorded reasons claim")

    unmapped = pkg_stats.get("packages_without_module_mapping") or {}
    unmapped_objs = sum(unmapped.values())
    mapped_total = pkg_stats.get("objects_mapped") or 0
    share = 100.0 * unmapped_objs / mapped_total if mapped_total else 0.0
    gate("packages without a module mapping cover < 5% of objects", share < 5.0,
         f"{len(unmapped)} packages, {unmapped_objs} objects = {share:.1f}%"
         + (f"  (largest: {', '.join(list(unmapped)[:3])})" if unmapped else ""),
         on_fail="WARN" if share < 15.0 else "FAIL")

    # --- per-object coverage ----------------------------------------------------------
    # The workbook now states a per-OBJECT figure, so it needs a gate of its own. The
    # honest denominator is every object scanned, and the only acceptable residue is a
    # module a human ruled out -- never "we could not tell".
    resid = cfg.work("residual.json")
    if resid.exists():
        st = json.loads(resid.read_text(encoding="utf-8"))
        if verbose:
            print("\nobject coverage")
        gate("every scanned object is accounted for (ticked or a recorded decision)",
             st.get("gaps", 1) == 0,
             f"{st.get('accounted_for')}/{st.get('objects')} = "
             f"{st.get('accounted_pct')}%; {st.get('gaps')} with no answer, "
             f"{st.get('ruled_out')} ruled out")
        min_obj = T.get("min_object_ticked_pct", 95.0)
        gate(f"objects with >= 1 tick >= {min_obj:.0f}%",
             st.get("coverage_pct", 0) >= min_obj,
             f"{st.get('covered')}/{st.get('objects')} = "
             f"{st.get('coverage_pct')}%")

    if verbose:
        print("\nadversarial")
    tp = [r["root_object"] for r in matrix
          if packages.get(r["root_object"], "") in cfg.excluded_packages
          or cfg.is_third_party_name(r["root_object"])]
    gate("no third-party rows on Sheet 1", not tp, f"{len(tp)} found {tp[:5]}")

    if cfg.core:
        worst_n, worst_m = max((sum(1 for r in matrix if r.get(m) == "X"), m)
                               for m in cfg.core)
        gate(f"no module exceeds {T['max_module_share_pct']:.0f}% of rows",
             100 * worst_n / n <= T["max_module_share_pct"],
             f"largest is {worst_m} at {100 * worst_n / n:.1f}%")

    dup = [k for k, v in collections.Counter(r["root_object"]
                                             for r in matrix).items() if v > 1]
    gate("no duplicate unit roots", not dup, f"{len(dup)} duplicates {dup[:5]}")

    empty_ev = [r["root_object"] for r in matrix
                if r.get("module_count") not in ("", "0") and not r.get("evidence")]
    gate("every ticked unit carries evidence", not empty_ev,
         f"{len(empty_ev)} ticked with no evidence")

    noise = [r["root_object"] for r in matrix
             if any(ig in (r.get("evidence") or "").upper()
                    for ig in cfg.std_call_ignore)]
    gate("framework noise never used as evidence", not noise,
         f"{len(noise)} found {noise[:3]}")

    # --- site assertions ---------------------------------------------------------------
    for a in cfg.assertions:
        name = a.get("name") or "site assertion"
        rx = re.compile(a["when_name_matches"], re.I) if a.get("when_name_matches") \
            else None
        pkg = (a.get("when_package") or "").upper()
        role = (a.get("when_role_contains") or "").lower()
        pool = []
        for r in matrix:
            if rx and not rx.search(r["root_object"]):
                continue
            if pkg and packages.get(r["root_object"], "").upper() != pkg:
                continue
            if role and role not in (r.get("role") or "").lower():
                continue
            pool.append(r)
        must = [m for m in a.get("must_tick", [])]
        bad = [r["root_object"] for r in pool
               if not all(r.get(m) == "X" for m in must)]
        if not pool:
            check(name, "WARN", "matched 0 units -- the assertion may be stale")
        else:
            gate(name, not bad,
                 f"{len(pool)} units matched, {len(bad)} missing "
                 f"{'+'.join(must)} {bad[:5]}",
                 on_fail=a.get("on_fail", "FAIL"))

    # --- stratified sample --------------------------------------------------------------
    rng = random.Random(cfg.seed)
    strata = {
        "HIGH, single tick": [r for r in matrix if r.get("confidence") == "HIGH"
                              and r.get("module_count") == "1"],
        "HIGH, multi tick": [r for r in matrix if r.get("confidence") == "HIGH"
                             and int(r.get("module_count") or 0) >= 2],
        "MEDIUM (name only)": [r for r in matrix if r.get("confidence") == "MEDIUM"],
        "LOW": [r for r in matrix if r.get("confidence") == "LOW"],
        "UNCLASSIFIED": [r for r in matrix if r.get("UNCLASSIFIED") == "X"],
        "parameterised T-Codes": [r for r in matrix
                                  if "parameterised" in r.get("role", "")],
        "no entry point": [r for r in matrix
                           if "no entry point" in r.get("role", "")],
        "forms": [r for r in matrix if "form" in r.get("role", "").lower()],
        "proposed module": [r for r in matrix if r.get("proposed_modules")],
    }
    sample = []
    for label, pool in strata.items():
        k = min(10, len(pool))
        for r in (rng.sample(pool, k) if pool else []):
            sample.append([label, r["unit_id"], r["root_object"], r["role"],
                           ",".join(m for m in cfg.all_modules if r.get(m) == "X"),
                           r.get("confidence", ""), r.get("evidence", "")[:160],
                           "", "", ""])
    spath = cfg.work("spotcheck_sample.csv")
    with spath.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["stratum", "unit_id", "root_object", "role", "machine_ticks",
                    "confidence", "evidence",
                    "reviewer_verdict(CORRECT/INCOMPLETE/WRONG)", "correct_modules",
                    "note"])
        w.writerows(sample)
    if verbose:
        print(f"\nstratified sample: {len(sample)} rows -> {cfg.rel(spath)} "
              f"(seed {cfg.seed}, reproducible)")

    report_path = write_report(cfg, results, matrix, misses, sample, ha, mrate,
                               prop_by_mod, unmapped, conflicts, rate)
    failed = [r for r in results if r[1] == "FAIL"]
    warned = [r for r in results if r[1] == "WARN"]
    if verbose:
        print(f"\n{len(results) - len(failed) - len(warned)}/{len(results)} checks "
              f"passed, {len(warned)} warned, {len(failed)} failed")
        if failed:
            print("FAILED: " + ", ".join(r[0] for r in failed))
        print(f"wrote {cfg.rel(report_path)}")
    return {"checks": len(results), "failed": [r[0] for r in failed],
            "warned": [r[0] for r in warned], "report": str(report_path)}


def write_report(cfg, results, matrix, misses, sample, ha, mrate, proposals,
                 unmapped, conflicts=(), agreement=None):
    n = len(matrix)
    passed = sum(1 for r in results if r[1] == "PASS")
    warned = sum(1 for r in results if r[1] == "WARN")
    failed = sum(1 for r in results if r[1] == "FAIL")
    L = ["# Appendix — Module Index validation", "",
         f"{len(results)} automated checks: **{passed} passed**, {warned} warned, "
         f"{failed} failed.", "",
         "| Check | Result | Detail |", "|---|---|---|"]
    for name, verdict, detail in results:
        L.append(f"| {name} | **{verdict}** | {detail} |")

    L += ["", "## Independent validation of rule R1", ""]
    if ha:
        L += ["The `package` column of the held-out export is never used as an input to "
              "the attribution, so it serves as independent truth for the package map "
              "that rule R1 depends on.", "",
              f"- Source: `{ha.get('source')}`",
              f"- Package assignment agreement: **{ha['rate']:.2f}%**"]
        if mrate is not None:
            L.append(f"- The module implied by that package is actually ticked: "
                     f"**{mrate:.2f}%**")
        L.append("")
        if misses:
            L += ["Cases where the implied module is *not* ticked (each one is a rule "
                  "defect to triage, not something to paper over with an override):",
                  "", "| Object | Expected | Ticked |", "|---|---|---|"]
            for obj, exp, got in misses:
                L.append(f"| `{obj}` | {', '.join(exp)} | {', '.join(got) or '—'} |")
            L.append("")
    else:
        L += ["**Not performed.** No held-out source is configured, so rule R1 — the "
              "only AUTHORITATIVE signal in the ladder — rests on the package map "
              "alone. Configure `validation.held_out` with any SAP-side export "
              "carrying object and package columns (ATC results, a cloud-readiness "
              "check, a custom-code register) and this becomes a hard number.", ""]

    if proposals or unmapped:
        L += ["## Open vocabulary", ""]
        if proposals:
            L += ["Modules named by the rules with no tick column in this "
                  "configuration:", "",
                  "| Module | Units | Strongest authority |", "|---|---:|---|"]
            for mod, rs in sorted(proposals.items(), key=lambda kv: -len(kv[1])):
                strongest = ("AUTHORITATIVE"
                             if any(r["authority"] == "AUTHORITATIVE" for r in rs)
                             else "STRONG"
                             if any(r["authority"] == "STRONG" for r in rs)
                             else "INFERRED/WEAK")
                L.append(f"| {mod} | {len(rs)} | {strongest} |")
            L += ["", "AUTHORITATIVE evidence here is a hard failure: an authoritative "
                  "signal named a business area the vocabulary does not contain, which "
                  "means the vocabulary is wrong, not the estate.", ""]
        if unmapped:
            L += [f"{len(unmapped)} package(s) carry objects with no module mapping "
                  f"({sum(unmapped.values())} objects). Rule R1 cannot fire for them.",
                  "", "| Package | Objects |", "|---|---:|"]
            for pkg, cnt in list(unmapped.items())[:15]:
                L.append(f"| `{pkg}` | {cnt} |")
            L.append("")
        L.append(f"Evidence and ready-made config snippets: "
                 f"`{cfg.out_prefix}-discovery.md`.")
        L.append("")

    if conflicts:
        L += ["## Content vs name — conflicts to triage", "",
              "Name evidence (what an object is called) and content evidence (which "
              "modules' standard tables it touches) are independent signals. Where "
              "both fire they agree on "
              + (f"**{agreement:.1f}%** of units" if agreement is not None
                 else "most units")
              + ". The rows below are where they do not, and each is worth one look: "
              "either the object legitimately serves another module's data, or a "
              "naming rule is wrong.", "",
              "| Unit | Tables suggest | Ticked |", "|---|---|---|"]
        for obj, content, ticked in conflicts:
            L.append(f"| `{obj}` | {', '.join(content)} | "
                     f"{', '.join(ticked) or '—'} |")
        L.append("")

    L += ["## Manual spot-check", "",
          f"`spotcheck_sample.csv` holds a stratified sample of **{len(sample)} "
          f"units**, drawn with a fixed seed ({cfg.seed}) so the sample is reproducible "
          "and re-auditable.", "",
          "Procedure per row: open the object in the source tree, read its description "
          "and first ~30 lines, **name the module from domain knowledge before reading "
          "the `evidence` column**, then compare and record `CORRECT` / `INCOMPLETE` / "
          "`WRONG`.", "",
          "Acceptance gate: ≥ 90% correct in the HIGH strata, ≥ 75% MEDIUM, ≥ 60% LOW. "
          "A `WRONG` verdict is a defect in the rule table — fix the rule, then "
          "re-run.", "",
          "| Stratum | Sampled |", "|---|---:|"]
    for label, c in collections.Counter(s[0] for s in sample).most_common():
        L.append(f"| {label} | {c} |")
    L += ["", f"_{n} units validated._", ""]
    out = cfg.out("-validation.md")
    out.write_text("\n".join(L), encoding="utf-8")
    return out
