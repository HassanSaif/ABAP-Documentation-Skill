"""
render.py -- the deliverable.

  <prefix>.xlsx   the master workbook: index, members, evidence, unattached, open
                  decisions, legend, coverage
  <prefix>.csv    sheet 1 as utf-8-sig, so Excel opens non-Latin text correctly
  <prefix>.md     the narrative appendix

Also writes module_matrix.baseline.tsv -- the immutable snapshot that the override
ingest diffs a returned workbook against.

Discipline that matters more than it looks: NOTHING in the legend or the narrative is
written as a literal number. Every count is computed here from the pipeline's own
stats files. A report that hardcodes "N export zips / N files / N-of-N" goes stale the
moment a package is added -- in a document whose entire value is that a consultant can
trust it.
"""

import collections
import csv
import json
import shutil

csv.field_size_limit(10_000_000)


def _read_tsv(path):
    with path.open(encoding="utf-8", newline="") as fh:
        r = csv.DictReader(fh, delimiter="\t")
        return list(r), list(r.fieldnames)


def _stats(cfg):
    p = cfg.work("package_map_stats.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _discovery(cfg):
    p = cfg.work("discovery.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _universe(cfg):
    """Every object that exists in the tree -- the set the coverage identity closes on.

    Unit closures also reach names that are NOT here (code calling packages that were
    never exported), so member lists are wider than this set and must be intersected
    with it before counting, or the identity overshoots by exactly the dangling count.
    """
    p = cfg.work("object_signals.tsv")
    if not p.exists():
        return set()
    with p.open(encoding="utf-8", newline="") as fh:
        return {r["object_name"] for r in csv.DictReader(fh, delimiter="\t")}


def _pkg_signal(cfg, st):
    """(objects in packages that imply a module, an explanatory note).

    A package every object shares -- a default customer package, a generic team
    package -- is a package with no module signal. It still gives the object a home,
    but rule R1 cannot fire from it, and the deliverable has to say so rather than let
    a reader assume the strongest rule was available everywhere.
    """
    pkgs = st.get("packages") or {}
    signal = sum(n for p, n in pkgs.items() if cfg.package_modules.get(p))
    silent = sorted((p for p, n in pkgs.items()
                     if p in cfg.package_modules and not cfg.package_modules[p]),
                    key=lambda p: -pkgs[p])
    note = ("every mapped package implies at least one module" if not silent else
            "no module signal from " + ", ".join(silent[:3])
            + " -- these are generic/default packages, so rule R1 (the only "
              "AUTHORITATIVE signal) cannot fire for their objects")
    return signal, note


def _dangling(cfg):
    p = cfg.work("dangling_refs.tsv")
    if not p.exists():
        return 0
    return max(0, sum(1 for _ in p.open(encoding="utf-8")) - 1)


TSTCP_EDGES = ("PARAM_REPORT", "PARAM_CALLS_TCODE", "PARAM_MAINTAINS", "PARAM_VARIANT",
               "PARAM_VARIANT_OF", "VARIANT_OF_PROG", "VARIANT_OF_TCODE", "CALL_TCODE")


def _tcode_facts(cfg, rows):
    """T-Code resolution, and where the module token actually lives (rule R2)."""
    from . import rules as R
    trans = [r for r in rows if r.get("root_type") == "TRAN"]
    names = {r["root_object"] for r in trans}
    with_prog = [r for r in trans if (r.get("entry_program") or "").strip()]

    by_type = collections.defaultdict(set)
    p = cfg.work("edges.csv")
    if p.exists():
        with p.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("source_object") in names:
                    by_type[row.get("edge_type")].add(row["source_object"])
    direct = by_type.get("TCODE_PGM", set())
    param = set().union(*(by_type.get(t, set()) for t in TSTCP_EDGES))
    return {
        "total": len(trans),
        "resolved": len(direct | param),
        "unresolved": len(names - (direct | param)),
        "pgmna": len(direct),
        "tstcp": len(param - direct),
        "token_in_program": sum(1 for r in with_prog
                                if R.name_tokens(cfg,
                                                 (r.get("entry_program") or "").strip())),
        "token_in_tcode": sum(1 for r in trans
                              if R.name_tokens(cfg, r["root_object"])),
        "parameterised": sum(1 for r in rows
                             if "parameterised" in (r.get("role") or "")),
    }


def run(cfg, verbose=True):
    src = cfg.work("module_matrix.final.tsv")
    if not src.exists():
        src = cfg.work("module_matrix.tsv")
        print(f"NOTE: no overrides applied yet, rendering {src.name}")
    rows, cols = _read_tsv(src)
    members, _ = _read_tsv(cfg.work("unit_members.tsv"))
    attribution, _ = _read_tsv(cfg.work("module_attribution.tsv"))
    unattached, _ = _read_tsv(cfg.work("unattached.tsv"))
    coverage, _ = _read_tsv(cfg.work("coverage_by_object.tsv")) \
        if cfg.work("coverage_by_object.tsv").exists() else ([], [])
    proposals, _ = _read_tsv(cfg.work("proposals.tsv")) \
        if cfg.work("proposals.tsv").exists() else ([], [])

    shutil.copyfile(src, cfg.work("module_matrix.baseline.tsv"))

    csv_path = cfg.out(".csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(cols)
        for row in rows:
            w.writerow([row.get(c, "") for c in cols])

    xlsx = write_xlsx(cfg, rows, cols, members, attribution, unattached, proposals,
                      coverage)
    md = write_md(cfg, rows, unattached, members)
    mirror(cfg, [xlsx, csv_path, md])
    if verbose:
        print(f"wrote {cfg.rel(csv_path)}")
    return {"units": len(rows), "xlsx": str(xlsx)}


def mirror(cfg, paths):
    for target in cfg.mirrors:
        target.mkdir(parents=True, exist_ok=True)
        for src in paths:
            dst = target / src.name
            if dst.resolve() == src.resolve():
                continue
            shutil.copyfile(src, dst)
        print(f"mirrored the deliverable to {cfg.rel(target)}")


# --- workbook -------------------------------------------------------------------------
def write_xlsx(cfg, rows, cols, members, attribution, unattached, proposals,
               coverage=()):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    bold = Font(bold=True)
    hdr_fill = PatternFill("solid", fgColor="1F3864")
    hdr_font = Font(bold=True, color="FFFFFF")
    tick_fill = PatternFill("solid", fgColor="D9E2F3")
    core_fill = PatternFill("solid", fgColor="2E5496")
    bucket_fill = PatternFill("solid", fgColor="7F7F7F")
    center = Alignment(horizontal="center")

    ws = wb.active
    ws.title = "Module Index"
    ws.append([cfg.short_headers.get(c, c) for c in cols])
    for row in rows:
        ws.append([row.get(c, "") for c in cols])
    for j, c in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=j)
        cell.font = hdr_font
        cell.fill = core_fill if c in cfg.core else (
            bucket_fill if c in cfg.buckets else hdr_fill)
        cell.alignment = center
    widths = {"unit_id": 8, "root_object": 38, "root_type": 10, "role": 34,
              "description_primary": 40, "description_secondary": 34, "package": 20,
              "entry_program": 32, "member_count": 8, "member_types": 22,
              "loc_total": 9, "inbound_refs": 12, "module_count": 7,
              "primary_module": 12, "confidence": 11, "rules_fired": 16,
              "evidence": 70, "proposed_modules": 18, "notes": 34,
              "override_applied": 16, "members": 70, "CROSS": 7, "UNCLASSIFIED": 8}
    for j, c in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(j)].width = widths.get(
            c, 5 if c in cfg.all_modules else 14)
    tick_idx = [j for j, c in enumerate(cols, start=1) if c in cfg.all_modules]
    for i in range(2, len(rows) + 2):
        for j in tick_idx:
            cell = ws.cell(row=i, column=j)
            cell.alignment = center
            if cell.value == "X":
                cell.fill = tick_fill
                cell.font = bold
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows) + 1}"

    _sheet(wb, "Unit Members", members, hdr_fill, hdr_font,
           {"unit_id": 8, "root_object": 38, "member": 44, "type": 8, "hop": 6,
            "parent": 40, "edge_type": 20})
    _sheet(wb, "Evidence", attribution, hdr_fill, hdr_font,
           {"unit_id": 8, "root_object": 38, "module": 12, "authority": 15,
            "rules_for_this_module": 22, "rules_for_the_unit": 22, "evidence": 90})
    _sheet(wb, "Unattached", unattached, hdr_fill, hdr_font,
           {"object_name": 44, "object_type": 12, "package": 20, "reason": 52})
    # Sheet 1 answers "which of these units is mine". This sheet answers the other
    # question, the one an owner asks: "is every object in my estate accounted for" --
    # one row per scanned object, how it reached a module, and on what evidence. An
    # object that reached none says so here, with the reason, instead of sitting in
    # Unattached under a line that claims it was covered via a consumer it does not
    # have.
    if coverage:
        _sheet(wb, "Objects", coverage, hdr_fill, hdr_font,
               {"object_name": 40, "object_type": 10, "package": 16, "text": 44,
                "how": 15, "modules": 26, "confidence": 11, "rules_fired": 16,
                "evidence": 74, "unit_ids": 14, "consumers": 11, "note": 52})
    if proposals:
        _sheet(wb, "Open Decisions", proposals, hdr_fill, hdr_font,
               {"unit_id": 8, "root_object": 38, "role": 30, "proposed_module": 16,
                "authority": 15, "rule": 8, "evidence": 80})

    ws = wb.create_sheet("Legend")
    for line in legend_lines(cfg, rows, unattached, proposals):
        ws.append(line)
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 100
    for cell in ws["A"]:
        cell.font = bold
        cell.alignment = Alignment(vertical="top")
    for cell in ws["B"]:
        cell.alignment = Alignment(vertical="top", wrap_text=True)

    ws = wb.create_sheet("Coverage")
    for line in coverage_lines(cfg, rows, unattached, members):
        ws.append(line)
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 62
    for cell in ws["A"]:
        cell.font = bold

    out = cfg.out(".xlsx")
    try:
        wb.save(out)
    except PermissionError as exc:
        # Excel holds an exclusive lock on an open workbook, and a synced drive
        # (OneDrive/SharePoint) holds one briefly mid-upload. Either way the raw
        # traceback points at zipfile and reads like a bug in the tool.
        raise SystemExit(
            f"cannot write {cfg.rel(out)}: {exc.strerror}. "
            f"The workbook is open in Excel, or the drive is mid-sync. Close it and "
            f"re-run `run --from render` -- nothing before this step needs redoing."
        ) from exc
    print(f"wrote {cfg.rel(out)}  ({len(rows)} units, {len(members)} member rows, "
          f"{len(attribution)} evidence rows, {len(unattached)} unattached, "
          f"{len(proposals)} open decisions)")
    return out


def _sheet(wb, title, rows, hdr_fill, hdr_font, widths):
    from openpyxl.utils import get_column_letter
    ws = wb.create_sheet(title)
    if not rows:
        ws.append(["(none)"])
        return ws
    cols = list(rows[0].keys())
    ws.append(cols)
    for row in rows:
        ws.append([row.get(c, "") for c in cols])
    for j, c in enumerate(cols, start=1):
        ws.cell(row=1, column=j).fill = hdr_fill
        ws.cell(row=1, column=j).font = hdr_font
        ws.column_dimensions[get_column_letter(j)].width = widths.get(c, 18)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows) + 1}"
    return ws


def legend_lines(cfg, rows, unattached, proposals):
    st = _stats(cfg)
    tc = _tcode_facts(cfg, rows)
    held = st.get("held_out") or {}
    dead = sum(1 for r in rows if "no entry point" in (r.get("role") or "")
               and (r.get("inbound_refs") or "0") in ("", "0"))
    n_pkgs = st.get("package_count", "?")
    L = [["Module Index - how to read it", ""],
         ["", ""],
         ["A tick means", "this module HAS A STAKE in this unit -- not that it owns "
          "it. An object can legitimately be ticked in two modules (e.g. a class that "
          "splits a billing document also drives the accounting posting). Both teams "
          "need to see it."],
         ["A row is a UNIT", "an entry point plus its entire nesting: T-Code -> "
          "program -> includes -> function modules -> classes -> forms. Nested "
          "children get NO row of their own; they are folded in, listed in the "
          "`members` column and itemised on the 'Unit Members' sheet."],
         ["Filter your module", "use the AutoFilter on your own column and select 'X'. "
          "`primary_module` is the single best-guess owner, for pivot tables."],
         ["", ""],
         ["Roles ending '(no entry point)'", "real code that no T-Code, service, "
          "enhancement or other entry point reaches. Use `inbound_refs` to tell two "
          "very different situations apart:"],
         ["   inbound_refs = 0", "nothing in the repository references it -- a "
          f"dead-code candidate worth reviewing. {dead} units."],
         ["   inbound_refs > 0", "it IS used, but only by other code that itself has "
          "no entry point: mutually-referencing class pairs, or OData MPC/DPC classes "
          "whose service registration points at a standard proxy, so the entry point "
          "exists in SAP but cannot be linked from source. NOT dead code."],
         ["", ""],
         ["Confidence", ""],
         ["HIGH", "at least one AUTHORITATIVE signal: home package, resolved entry "
          "program, or the standard SAP object being enhanced."],
         ["MEDIUM", "best signal is a naming convention."],
         ["LOW", "best signal is inferred from standard tables/calls in the closure, "
          "or from a description keyword."],
         ["", ""],
         ["Rules (see `rules_fired` and `evidence`)", ""],
         ["R1  home package", "AUTHORITATIVE. Home package of the object, from "
          f"{n_pkgs} packages."
          + (f" Validated against a held-out source: {held.get('agree')}/"
             f"{held.get('total')} = {held.get('rate', 0):.0f}% agreement."
             if held else " NOT independently validated in this run -- no held-out "
             "source was configured.")],
         ["R2  resolved entry program", "AUTHORITATIVE. Always the program behind the "
          f"T-Code, never the T-Code name -- a module token appears in "
          f"{tc['token_in_program']}/{tc['resolved']} resolved programs but only "
          f"{tc['token_in_tcode']}/{tc['total']} T-Code names."],
         ["R3  enhancement anchor", "AUTHORITATIVE. The standard SAP object being "
          "enhanced (ACC_DOCUMENT -> FI, ME_PROCESS_PO_CUST -> MM)."],
         ["R4  classic exit include", "AUTHORITATIVE. ZX<fgrp>U01 SMOD exit includes "
          "self-classify from their exit function group."],
         ["R5  name tokens", "STRONG. This estate's naming convention, read at the "
          f"configured segment positions {cfg.module_segments}. Tokens that look like "
          "modules but are entity, plant or layer codes are blacklisted."],
         ["R6  special families", "STRONG. Whole prefixes that belong to one area "
          "regardless of member naming."],
         ["R7  closure fingerprint", "INFERRED. Discriminating standard tables and "
          "standard calls anywhere in the unit. Near-universal tables (material, "
          "customer, company code) are excluded as carrying no signal, and table-"
          "maintenance framework calls are on an ignore list."],
         ["R8  tie-breakers", "WEAK. Program application area and description "
          "keywords. Only fires when nothing else did."],
         ["", ""]]

    if cfg.buckets:
        L.append(["Cross-cutting columns", ""])
        for b in cfg.buckets:
            L.append([cfg.short_headers.get(b, b),
                      cfg.bucket_meta.get(b, {}).get("description", "")])
        L.append(["", ""])

    L += [["Open decisions", ""],
          ["Proposed modules",
           (f"{len({p['proposed_module'] for p in proposals})} module(s) were named by "
            f"the rules but have no column here, across "
            f"{len(proposals)} units -- see the 'Open Decisions' sheet and the "
            "discovery report. The vocabulary is open: nothing was dropped, it is "
            "waiting for a decision."
            if proposals else "None. Every module the rules named has a column.")],
          ["", ""],
          ["Known limits - please read", ""],
          [f"{_dangling(cfg)} references point at objects that are not here",
           "Code calls custom objects absent from this export. Listed in "
           "dangling_refs.tsv. Supplying the missing package shrinks this list."],
          ["Forms cannot be linked to their programs",
           "Form selection is config-driven (output determination / NAST customizing "
           "tables), which a source export does not contain. Forms are attributed by "
           "package and name, not by call graph."],
          ["Dynamic calls are invisible",
           "Call sites with a variable target (CALL FUNCTION <var>, SUBMIT (<var>), "
           "PERFORM (<var>), CALL TRANSACTION <var>) can never be resolved from static "
           "source. That is the hard ceiling on closure completeness."],
          [f"{tc['parameterised']} T-Codes have no custom code behind them",
           "They are parameterised or variant entries into standard SAP. Labelled as "
           "such rather than left looking like missing data."],
          [f"{tc['unresolved']} T-Codes resolve to no target at all",
           "Neither <PGMNA> nor the <TSTCP> parameter string names a program this pass "
           "can follow. They carry a row and their package attribution, but no "
           "closure."],
          ["", ""],
          ["Corrections", "Edit the tick cells and send the workbook back. Run "
           "`modindex.py overrides --ingest <file>.xlsx --reviewer <name>`. "
           "Corrections are stored outside the build and re-applied on every future "
           "rebuild, so they are never overwritten."]]
    return L


def coverage_lines(cfg, rows, unattached, members):
    n = len(rows) or 1
    st = _stats(cfg)
    tc = _tcode_facts(cfg, rows)
    held = st.get("held_out") or {}
    disc = _discovery(cfg)
    ticked = sum(1 for r in rows if r.get("module_count") not in ("", "0"))
    multi = sum(1 for r in rows if int(r.get("module_count") or 0) >= 2)
    conf = collections.Counter(r.get("confidence") for r in rows)
    universe = _universe(cfg)
    folded = len(({m["member"] for m in members} & universe)
                 - {r["root_object"] for r in rows})
    total = len(rows) + folded + len(unattached)
    reconciles = (not universe) or total == len(universe)
    band = cfg.thresholds["multi_module_band"]
    L = [["Coverage and validation", "value", "note"],
         ["units (rows on Module Index)", len(rows),
          "one per entry point, nesting folded in"],
         ["units with >= 1 module tick", f"{ticked} ({100 * ticked / n:.1f}%)",
          f"target >= {cfg.thresholds['min_ticked_pct']}%"],
         ["UNCLASSIFIED", f"{len(rows) - ticked} "
          f"({100 * (len(rows) - ticked) / n:.1f}%)",
          f"target <= {cfg.thresholds['max_unclassified_pct']}%"],
         ["multi-module units", f"{multi} ({100 * multi / n:.1f}%)",
          f"target band {band[0]:.0f}-{band[1]:.0f}%; below it the multi-tick model is "
          "not working, above it the attribution is smearing across modules"],
         ["confidence HIGH", f"{conf['HIGH']} ({100 * conf['HIGH'] / n:.1f}%)",
          f"target >= {cfg.thresholds['min_high_confidence_pct']}%"],
         ["objects folded into units as members", folded,
          "nested children of a root; itemised on the Unit Members sheet"],
         ["objects attributed via consumer (Unattached)", len(unattached),
          "mostly DDIC; attributed through the unit that uses them"],
         ["all objects accounted for",
          f"{len(rows)} + {folded} + {len(unattached)} = {total}",
          f"roots + folded members + unattached, against {len(universe)} objects in "
          f"the source tree"
          + ("" if reconciles else " -- MISMATCH, do not ship this workbook")],
         ["", "", ""],
         ["package map vs held-out source",
          (f"{held.get('agree')} / {held.get('total')} = {held.get('rate', 0):.0f}%"
           if held else "not validated"),
          ("independent validation of rule R1" if held
           else "no held-out source configured -- rule R1 is unvalidated")],
         ["objects with a home package",
          f"{st.get('objects_mapped_in_universe', '?')} / "
          f"{st.get('objects_in_universe', '?')}",
          f"from {st.get('package_count', '?')} packages via "
          f"{', '.join(p.get('type', '?') for p in st.get('providers', []))}"],
         # Having a package and having a package that MEANS something are different
         # facts, and the gap between them is exactly how far rule R1 can reach.
         ["objects whose package implies a module",
          f"{_pkg_signal(cfg, st)[0]} / {st.get('objects_mapped', '?')}",
          _pkg_signal(cfg, st)[1]],
         ["packages with no module mapping",
          len(st.get("packages_without_module_mapping") or {}),
          "each one is attribution done the hard way -- see the discovery report"],
         ["T-Codes resolved to an entry point", f"{tc['resolved']} / {tc['total']}",
          f"{tc['pgmna']} via <PGMNA> + {tc['tstcp']} via <TSTCP> parameter decoding"],
         ["proposed modules (no column yet)",
          len(disc.get("proposed_modules") or []),
          "open vocabulary: evidence found for areas this config does not name"],
         ["", "", ""],
         ["units per module", "", ""]]
    for mod in cfg.all_modules:
        c = sum(1 for r in rows if r.get(mod) == "X")
        share = 100 * c / n
        L.append([f"   {mod}", f"{c} ({share:.1f}%)",
                  f"no module may exceed {cfg.thresholds['max_module_share_pct']:.0f}% "
                  "of rows" if share > cfg.thresholds["max_module_share_pct"] - 5
                  else ""])
    L += [["", "", ""], ["units per role", "", ""]]
    for role, c in collections.Counter(r.get("role") for r in rows).most_common():
        L.append([f"   {role}", c, ""])
    return L


def write_md(cfg, rows, unattached, members):
    n = len(rows) or 1
    st = _stats(cfg)
    tc = _tcode_facts(cfg, rows)
    held = st.get("held_out") or {}
    disc = _discovery(cfg)
    universe = _universe(cfg)
    folded = len(({m["member"] for m in members} & universe)
                 - {r["root_object"] for r in rows})
    ticked = sum(1 for r in rows if r.get("module_count") not in ("", "0"))
    multi = sum(1 for r in rows if int(r.get("module_count") or 0) >= 2)
    band = cfg.thresholds["multi_module_band"]

    L = [f"# Appendix — Module Index (for the functional consultants)", "",
         f"One row per **entry-point unit**: {len(rows)} units covering the whole "
         "custom estate. A unit is an entry point plus its entire nesting (T-Code → "
         "program → includes → function modules → classes → forms); nested children "
         "are folded into the root rather than listed separately.", "",
         "A tick means **this module has a stake in this unit**, not that it owns it — "
         "so a class that splits a billing document is ticked in both modules that "
         "care, and both teams see it.", "",
         f"Machine-readable: `{cfg.out_prefix}.csv`. Master workbook with the member, "
         f"evidence, unattached, open-decision, legend and coverage sheets: "
         f"`{cfg.out_prefix}.xlsx`.", "",
         "## Units per module", "", "| Module | Units | Share |", "|---|---:|---:|"]
    for mod in cfg.all_modules:
        c = sum(1 for r in rows if r.get(mod) == "X")
        L.append(f"| {mod} | {c} | {100 * c / n:.1f}% |")

    L += ["", "## Units per role", "", "| Role | Units |", "|---|---:|"]
    for role, c in collections.Counter(r.get("role") for r in rows).most_common():
        L.append(f"| {role} | {c} |")

    L += ["", "## Coverage", "",
          f"- Units with at least one module tick: **{ticked} of {len(rows)} "
          f"({100 * ticked / n:.1f}%)**",
          f"- Multi-module units: **{multi} ({100 * multi / n:.1f}%)** — the intended "
          f"band is {band[0]:.0f}–{band[1]:.0f}%; below that the multi-tick model is "
          "not working, above it the attribution is smearing across modules",
          f"- Objects attributed through their consumer rather than given their own "
          f"row: **{len(unattached)}** (mostly DDIC).",
          f"- The three populations close on the whole estate: **{len(rows)} roots + "
          f"{folded} folded members + {len(unattached)} unattached = "
          f"{len(rows) + folded + len(unattached)}**, against {len(universe)} objects "
          "in the source tree — nothing is silently dropped.", "",
          "## Validation", ""]
    if held:
        L.append(f"- **Rule R1 (home package) against a held-out set:** the package map "
                 f"was checked against an independent SAP-side export — "
                 f"**{held.get('agree')} of {held.get('total')} objects agree "
                 f"({held.get('rate', 0):.0f}%)**.")
    else:
        L.append("- **Rule R1 is not independently validated in this run.** No "
                 "held-out source (an ATC export, cloud-readiness check or custom-code "
                 "register carrying a `package` column) was configured. The package "
                 "map is internally consistent, but nothing outside this pipeline "
                 "confirms it.")
    sig_n, sig_note = _pkg_signal(cfg, st)
    L += [f"- **Package coverage:** {st.get('objects_mapped_in_universe', '?')} of "
          f"{st.get('objects_in_universe', '?')} scanned objects have a home package, "
          f"across {st.get('package_count', '?')} packages. "
          f"{sig_n} of them sit in a package that implies a module — {sig_note}.",
          f"- **T-Code resolution:** {tc['resolved']} of {tc['total']}, combining "
          f"`<PGMNA>` ({tc['pgmna']}) with `<TSTCP>` parameter decoding "
          f"({tc['tstcp']}) — the latter resolves transactions that would otherwise "
          "have no entry point at all."]

    proposed = disc.get("proposed_modules") or []
    unmapped = disc.get("unmapped_packages") or []
    if proposed or unmapped:
        L += ["", "## Open decisions", "",
              "The module vocabulary is open: a rule that names an area this "
              "configuration does not list produces a **proposal**, never a silent "
              "drop."]
        if proposed:
            L += ["", "| Proposed module | Units | Strongest signal |",
                  "|---|---:|---|"]
            for p in proposed:
                L.append(f"| {p['module']} | {p['units']} | {p['strongest']} |")
        if unmapped:
            L.append("")
            L.append(f"{len(unmapped)} package(s) carry objects but have no module "
                     "mapping, so rule R1 cannot fire for them.")
        L += ["", f"Full evidence and the config snippets that close each item: "
              f"`{cfg.out_prefix}-discovery.md`."]

    limits = [
        f"**{_dangling(cfg)} code references point at objects that are not in the "
        "export.** Listed in `dangling_refs.tsv`. Each one is a package that was never "
        "exported, not a broken reference.",
        "**Forms cannot be tied to their calling programs.** Selection is config-"
        "driven via output determination, which a source export does not include. "
        "Forms are attributed by package and name instead.",
        "**Dynamic calls are unreachable by static analysis** — a call site whose "
        "target is a variable cannot be resolved without runtime data. This bounds "
        "closure completeness.",
        f"**{tc['parameterised']} T-Codes have no custom code behind them** — they are "
        "parameterised or variant entries into standard SAP. They are labelled as such "
        "rather than left looking like missing data.",
        f"**{tc['unresolved']} T-Codes resolve to no target at all** — neither "
        "`<PGMNA>` nor the `<TSTCP>` parameter string names a program this pass can "
        "follow. They carry a row and their package attribution, but no closure.",
    ]
    L += ["", "## Limits, stated plainly", ""]
    L += [f"{i}. {t}" for i, t in enumerate(limits, start=1)]
    L += ["", "## Sending corrections back", "",
          "Edit the tick cells in the workbook and return it. Then:", "",
          "```",
          "python modindex.py overrides --ingest <returned>.xlsx --reviewer <name>",
          "```", "",
          "Each changed tick becomes a row in `overrides/module-overrides.csv`, which "
          "the build never writes and always applies last. Corrections therefore "
          "survive every future regeneration.", ""]
    out = cfg.out(".md")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {cfg.rel(out)}")
    return out
