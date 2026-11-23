"""
overrides.py -- consultant corrections, applied last, and permanent.

The contract, and the whole reason this step exists: corrections live ONLY in
overrides/module-overrides.csv, which the pipeline NEVER writes. Everything else is
regenerated from source on every run, so a correction stored anywhere else -- in the
matrix, in the workbook, in a rule table -- is destroyed the next time somebody
rebuilds. Being able to promise "your corrections survive every future regeneration"
is what makes a consultant willing to review thousands of rows.

Two modes:
  apply    module-overrides.csv -> module_matrix.final.tsv
  ingest   diff a consultant's edited workbook against the baseline snapshot and
           APPEND one ADD/REMOVE row per changed tick

Consultants return an edited .xlsx, not hand-written CSV, so ingest is the realistic
channel. It refuses to run when the returned workbook's rows do not line up with the
baseline -- which is exactly what happens when someone sorts or filters and saves, and
silently ingesting that would scramble every correction.
"""

import collections
import csv
import datetime
import sys

HEADER = ["unit_id", "root_object", "module", "action", "reviewer", "review_date",
          "reason"]
ACTIONS = {"ADD", "REMOVE", "CROSS", "ROLE", "EXCLUDE"}

csv.field_size_limit(10_000_000)


def override_path(cfg):
    d = cfg.work_dir / "overrides"
    d.mkdir(parents=True, exist_ok=True)
    return d / "module-overrides.csv"


def ensure_template(cfg):
    path = override_path(cfg)
    if path.exists():
        return path
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(HEADER)
        # The '#' must be in root_object -- that is the field the loader tests.
        w.writerow(["", "# EXAMPLE - delete this row. ZEXAMPLE_OBJECT",
                    cfg.all_modules[0], "REMOVE", "reviewer.name", "2026-01-01",
                    "why the machine verdict is wrong"])
    (path.parent / "README.md").write_text(
        "# module-overrides.csv\n\n"
        "Hand-maintained. **The build never writes this file** — it is the only place "
        "a human correction survives a regeneration.\n\n"
        "One row per (unit, module) correction. Keyed on `root_object` + `module`, so "
        "two reviewers can edit disjoint rows without conflicting.\n\n"
        "| column | meaning |\n|---|---|\n"
        "| `unit_id` | optional; `root_object` is the real key (unit ids shift between "
        "runs) |\n"
        "| `root_object` | the object in the `root_object` column of the workbook |\n"
        "| `module` | one of " + ", ".join(cfg.all_modules) +
        "; or `*` with action `CROSS` |\n"
        "| `action` | `ADD` · `REMOVE` · `CROSS` · `ROLE` · `EXCLUDE` |\n"
        "| `reviewer` | who decided |\n| `review_date` | YYYY-MM-DD |\n"
        "| `reason` | why — this is what makes the correction auditable later |\n\n"
        "Lines starting with `#` are ignored.\n\n"
        "To ingest an edited workbook instead of writing rows by hand:\n\n"
        "```\npython modindex.py overrides --ingest <returned>.xlsx "
        "--reviewer <name>\n```\n",
        encoding="utf-8")
    print(f"created override template {cfg.rel(path)}")
    return path


def load(cfg):
    path = override_path(cfg)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            ro = (row.get("root_object") or "").strip()
            if not ro or ro.startswith("#"):
                continue
            act = (row.get("action") or "").strip().upper()
            if act not in ACTIONS:
                print(f"  WARNING: unknown action {act!r} for {ro} -- skipped")
                continue
            out.append({"root_object": ro.upper(),
                        "module": (row.get("module") or "").strip().upper(),
                        "action": act,
                        "reviewer": (row.get("reviewer") or "").strip(),
                        "date": (row.get("review_date") or "").strip(),
                        "reason": (row.get("reason") or "").strip()})
    return out


def _load_matrix(path):
    with path.open(encoding="utf-8", newline="") as fh:
        r = csv.DictReader(fh, delimiter="\t")
        return list(r), list(r.fieldnames)


def apply(cfg, verbose=True):
    ensure_template(cfg)
    # The residual pass may have rescued units that ended with no tick at all. It
    # writes a separate file rather than editing the attribution in place, so the two
    # are always distinguishable -- and so re-running either step stays idempotent.
    src = cfg.work("module_matrix.residual.tsv")
    if not src.exists():
        src = cfg.work("module_matrix.tsv")
    rows, cols = _load_matrix(src)
    by_root = collections.defaultdict(list)
    for row in rows:
        by_root[row["root_object"].upper()].append(row)

    overrides = load(cfg)
    applied = stale = redundant = 0
    for o in overrides:
        targets = by_root.get(o["root_object"])
        if not targets:
            print(f"  STALE override: {o['root_object']} no longer exists as a "
                  "unit root")
            stale += 1
            continue
        for row in targets:
            stamp = f"override:{o['reviewer'] or 'unknown'}@{o['date'] or 'n/a'}"
            if o["action"] == "ADD":
                if o["module"] not in cfg.all_modules:
                    print(f"  WARNING: override ADD names {o['module']}, which has no "
                          "tick column -- adopt the module first")
                    continue
                if row.get(o["module"]) == "X":
                    redundant += 1
                    continue
                row[o["module"]] = "X"
            elif o["action"] == "REMOVE":
                if row.get(o["module"]) != "X":
                    redundant += 1
                    continue
                row[o["module"]] = ""
            elif o["action"] == "CROSS":
                row["CROSS"] = "X"
            elif o["action"] == "EXCLUDE":
                row["_drop"] = "1"
            elif o["action"] == "ROLE":
                row["role"] = o["reason"] or row["role"]
            row["override_applied"] = (
                (row.get("override_applied", "") + "; "
                 if row.get("override_applied") else "")
                + f"{o['action']}:{o['module'] or '*'}")
            row["evidence"] = (row.get("evidence", "") + "; " + stamp).strip("; ")
            applied += 1

    rows = [r for r in rows if not r.get("_drop")]
    for row in rows:
        mods = [m for m in cfg.all_modules if row.get(m) == "X"]
        row["module_count"] = len(mods)
        row["UNCLASSIFIED"] = "" if mods else "X"
        if row["primary_module"] not in mods:
            row["primary_module"] = mods[0] if mods else ""

    out_cols = [c for c in cols if c != "_drop"]
    if "override_applied" not in out_cols:
        out_cols.insert(out_cols.index("notes"), "override_applied")
    out = cfg.work("module_matrix.final.tsv")
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(out_cols)
        for row in rows:
            w.writerow([row.get(c, "") for c in out_cols])

    if verbose:
        print(f"overrides in file: {len(overrides)}")
        print(f"  applied         {applied}")
        print(f"  stale           {stale}  (unit root no longer exists)")
        print(f"  redundant       {redundant}  (machine verdict now agrees -- "
              "retire these)")
        print(f"units out: {len(rows)}")
        print(f"wrote {cfg.rel(out)}")
    return {"overrides": len(overrides), "applied": applied, "stale": stale,
            "redundant": redundant, "units": len(rows)}


def ingest(cfg, xlsx_path, reviewer):
    try:
        import openpyxl
    except ImportError:
        sys.exit("openpyxl required for ingest: pip install openpyxl")
    baseline_path = cfg.work("module_matrix.baseline.tsv")
    if not baseline_path.exists():
        sys.exit(f"no baseline snapshot at {cfg.rel(baseline_path)} -- run `render` "
                 "first")
    base, _cols = _load_matrix(baseline_path)

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Module Index"] if "Module Index" in wb.sheetnames else wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    hdr = [str(c or "") for c in next(it)]
    # Sheet 1 headers may be the short bucket labels rather than the internal names.
    inverse = {v: k for k, v in cfg.short_headers.items()}
    idx = {inverse.get(name, name): i for i, name in enumerate(hdr)}
    if "root_object" not in idx:
        sys.exit("returned workbook has no root_object column")

    returned = []
    for vals in it:
        if vals is None or all(v is None for v in vals):
            continue
        returned.append({name: (vals[i] if i < len(vals) else None)
                         for name, i in idx.items()})

    if len(returned) != len(base):
        sys.exit(f"row-count mismatch: workbook {len(returned)} vs baseline "
                 f"{len(base)}. The workbook was probably sorted/filtered and saved -- "
                 "re-export and edit ticks only.")
    for i, (rrow, brow) in enumerate(zip(returned, base), start=2):
        if str(rrow.get("root_object") or "").upper() != brow["root_object"].upper():
            sys.exit(f"row {i} is {rrow.get('root_object')!r}, baseline has "
                     f"{brow['root_object']!r} -- row order changed, refusing to "
                     "ingest")

    today = datetime.date.today().isoformat()
    new = []
    for rrow, brow in zip(returned, base):
        for mod in cfg.all_modules:
            was = brow.get(mod, "") == "X"
            now = str(rrow.get(mod) or "").strip().upper() == "X"
            if was == now:
                continue
            new.append([brow["unit_id"], brow["root_object"], mod,
                        "ADD" if now else "REMOVE", reviewer, today,
                        "ingested from returned workbook"])

    if not new:
        print("no tick changes found -- nothing to append")
        return {"appended": 0}
    path = ensure_template(cfg)
    with path.open("a", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows(new)
    print(f"appended {len(new)} override rows to {cfg.rel(path)}")
    for row in new[:20]:
        print(f"  {row[3]:<6} {row[2]:<12} {row[1]}")
    if len(new) > 20:
        print(f"  ... and {len(new) - 20} more")
    return {"appended": len(new)}
