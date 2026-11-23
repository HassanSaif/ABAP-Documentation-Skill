"""
unresolved.py -- the names the rules could not settle, and where to go to settle them.

Every estate contains standard SAP names the knowledge base has never heard of. A
transaction variant over `IH09`, an enhancement hanging off `SAPLWPUE`, a parameter
transaction entering `RIMARA20` -- if none of those is in the rule tables, the unit
either gets a weak tick from somewhere else or none at all, and the reason disappears
into a LOW-confidence row nobody looks at twice.

That is a research task, not a tuning task, and it has a fixed procedure:

    the name is a Z object   ->  it is in this repository. Find it, read the tables it
                                reads and writes, and classify from those.
    the name is standard     ->  it is documented publicly. Look up what the
                                transaction or program actually DOES -- not which menu
                                it is filed under.
    a transaction variant    ->  it names its T-Code in <TCODE> and its program in
                                <GUI_PROG>. Resolve those, by the two rules above.
    neither answers          ->  ask the owner. A stated question beats a quiet guess.

This module produces the worklist that procedure runs on, ranked by how many units each
unknown name affects, so the twenty minutes of research go to the name that settles
forty rows rather than the one that settles one.

Why it earns its place: a rule table saying `^IH\\d -> PM` -- because SAP files the
whole IH0x family under Plant Maintenance -- leaves `IH09` with no module at all on an
estate where PM is out of scope, and takes every parameter transaction and variant
built on it down too. Thirty seconds of looking it up says IH09 is
*Display Material*, program RIMARA20, a report over MARA -- a PM transaction whose
subject is the material master. It needed both ticks, and nothing in the repository was
ever going to say so.

Output
  unresolved_names.tsv   one row per unknown name: what kind, where to look, how many
                         units it affects, and whether it is Z (in the repo) or standard
"""

import collections
import csv

csv.field_size_limit(10_000_000)

COLUMNS = ["name", "kind", "where_to_look", "units_affected", "example_units",
           "current_verdict", "edge_types"]


def _is_custom(cfg, name):
    """Custom-namespace test that sees through the module-pool wrapper.

    'SAPMZ_FOO' is a CUSTOM module pool and 'SAPLZIDOC' a custom function group, but
    both begin with 'S', so a test on the raw name calls them standard SAP objects and
    the worklist sends a human off to look up a name that only exists in this
    repository.
    """
    from . import names as N
    n = (name or "").upper()
    for lead in ("SAPL", "SAPM", "SAPF"):
        if n.startswith(lead) and len(n) > len(lead):
            n = n[len(lead):]
            break
    return N.is_custom(n, cfg.custom_prefixes)


def run(cfg, verbose=True):
    from . import rules as R

    scanned = set()
    with cfg.work("object_signals.tsv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            scanned.add(row["object_name"])

    # Every unit's own verdict, so the worklist can say what is currently riding on
    # each unknown name. A name that only ever appears on HIGH-confidence rows is not
    # worth researching; the same name on eleven LOW rows is.
    units, unit_conf = {}, {}
    matrix = cfg.work("module_matrix.final.tsv")
    if not matrix.exists():
        matrix = cfg.work("module_matrix.residual.tsv")
    if not matrix.exists():
        matrix = cfg.work("module_matrix.tsv")
    with matrix.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            units[row["root_object"]] = row["unit_id"]
            mods = [m for m in cfg.all_modules if (row.get(m) or "").strip()]
            unit_conf[row["root_object"]] = (
                row.get("confidence") or "NONE",
                ",".join(mods) or "(no tick)")

    # Candidate names: whatever a unit ENTERS through or an enhancement ANCHORS on.
    # Those are the two places a single unknown name decides a whole row.
    interesting = set(cfg.entry_edges) | set(cfg.anchor_edges)
    hits = collections.defaultdict(lambda: {"units": set(), "edges": set()})
    with cfg.work("edges.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["edge_type"] not in interesting:
                continue
            tgt, src = row["target_object"], row["source_object"]
            if not tgt or tgt in scanned:
                continue          # in the repo, or resolved as an object already
            if tgt.upper().startswith(cfg.std_name_ignore) \
                    or cfg.is_generated_name(tgt):
                continue          # known, and known to carry no business meaning
            # Every rule that can settle a bare name, not just the four that were here
            # first: R12 resolved MP200000 while the worklist still asked a human to
            # research it, which is the sort of thing that trains people to skip the
            # report.
            if (R.wrapper_hits(cfg, tgt) or R.badi_hits(cfg, tgt)
                    or R.std_anchor_hits(cfg, tgt) or R.name_tokens(cfg, tgt)
                    or R.exit_include_hits(cfg, tgt)
                    or R.infotype_hits(cfg, tgt) or R.append_hits(cfg, tgt)
                    or R.fugr_include_hits(cfg, tgt)
                    or R.idoc_hits(cfg, tgt, "")
                    or R.family_hits(cfg, tgt)):
                continue          # some rule already knows this name
            hits[tgt]["units"].add(src)
            hits[tgt]["edges"].add(row["edge_type"])

    rows = []
    for name, info in hits.items():
        custom = _is_custom(cfg, name)
        if name.upper().startswith("AQ") and "=" in name:
            kind = "generated SAP Query report"
            where = ("neither the query nor its user group is in this export. The "
                     "query object was not serialised; the transaction is attributable "
                     "from its own name, and this is a stated export gap")
        elif custom:
            kind = "custom name, not in this export"
            where = ("it belongs to this estate: find it in the repository and "
                     "classify from the tables it reads and writes. If it is genuinely "
                     "absent it was never exported -- say so as a stated limit")
        else:
            kind = "standard SAP name"
            where = ("look up what it DOES, not which menu it sits under; then add it "
                     "to std_name_wrappers (a LIST if it owns one module and displays "
                     "another's data, owner first)")
        affected = sorted(info["units"])
        # A source that is not a unit ROOT has no verdict of its own -- it is a member
        # of somebody else's unit. Reporting that as "NONE" reads as "this row has no
        # tick", which is a different and much more alarming statement.
        verdicts = collections.Counter(
            unit_conf[u][0] if u in unit_conf else "(member, not a root)"
            for u in affected)
        rows.append([
            name, kind, where, len(affected), ";".join(affected[:4]),
            ", ".join(f"{k}:{v}" for k, v in verdicts.most_common()),
            ";".join(sorted(info["edges"])),
        ])
    rows.sort(key=lambda r: (-r[3], r[0]))

    out = cfg.work("unresolved_names.tsv")
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(COLUMNS)
        w.writerows(rows)

    std = [r for r in rows if r[1] == "standard SAP name"]
    zed = [r for r in rows if r[1] != "standard SAP name"]
    stats = {"unresolved": len(rows), "standard": len(std), "custom": len(zed),
             "units_affected": len({u for _n, i in hits.items()
                                    for u in i["units"]})}
    if verbose:
        print(f"unresolved entry/anchor names: {len(rows)} "
              f"({len(std)} standard, {len(zed)} custom) "
              f"affecting {stats['units_affected']} units")
        for r in rows[:15]:
            print(f"  {r[3]:>4} units  {r[0]:<28} {r[1]:<28} [{r[5]}]")
        if len(rows) > 15:
            print(f"  ... {len(rows) - 15} more in {cfg.rel(out)}")
        print(f"\nwrote {cfg.rel(out)}")
    return stats


def report_lines(cfg):
    """Markdown for the discovery report -- the human-facing half of the worklist."""
    path = cfg.work("unresolved_names.tsv")
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    if not rows:
        return ["## Names to research", "",
                "None. Every object a unit enters through, and every object an "
                "enhancement anchors on, resolved to a module through the rule "
                "tables.", ""]
    out = ["## Names to research", "",
           "Each of these is a name the rules could not settle -- something a unit "
           "enters through, or an enhancement hangs off. They are ranked by how many "
           "units ride on them, so the research goes where it pays.", "",
           "The procedure is fixed:", "",
           "1. **A `Z`/`Y` name** is in this repository. Find it, read the tables it "
           "reads and writes, classify from those.",
           "2. **A standard name** is documented publicly. Look up what it *does* -- "
           "not which menu SAP files it under. Those differ, and the difference has "
           "cost objects their module.",
           "3. **A transaction variant** names its T-Code in `<TCODE>` and its program "
           "in `<GUI_PROG>`. Resolve those by rules 1 and 2; the program is the more "
           "informative of the two.",
           "4. **If neither the repository nor the documentation answers, ask the "
           "owner.** A stated question beats a quiet guess, and one answer usually "
           "settles a whole family.", "",
           "| Name | Kind | Units | Currently | Reached through |",
           "|---|---|---:|---|---|"]
    for r in rows[:40]:
        out.append(f"| `{r['name']}` | {r['kind']} | {r['units_affected']} | "
                   f"{r['current_verdict']} | {r['edge_types']} |")
    if len(rows) > 40:
        out.append(f"\n… and {len(rows) - 40} more in "
                   f"`{cfg.rel(cfg.work('unresolved_names.tsv'))}`.")
    out.append("")
    return out
