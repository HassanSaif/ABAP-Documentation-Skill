# The deliverable, and the correction loop

## What gets produced

| File | For whom |
|---|---|
| `<prefix>.xlsx` | the functional consultants — the master workbook |
| `<prefix>.csv` | anyone scripting against it (utf-8-sig, so Excel opens non-Latin text correctly) |
| `<prefix>.md` | the report appendix: units per module, per role, coverage, validation, limits |
| `<prefix>-validation.md` | the evidence that the index is sound, gate by gate |
| `<prefix>-discovery.md` | the open decisions: unmapped packages, proposed modules, unclassified naming segments |

## Workbook anatomy

| Sheet | Contents | Why it is there |
|---|---|---|
| **Module Index** | one row per unit, tick columns per module, evidence, confidence | the deliverable |
| **Unit Members** | every folded child: unit, member, type, hop, parent, edge type | "why is this object in that unit?" — answered without asking you |
| **Evidence** | long form: unit × module × authority × rules × evidence | "why is this ticked SD?" |
| **Unattached** | every object with no row, and the reason | proves nothing was dropped |
| **Open Decisions** | out-of-vocabulary module evidence | the open vocabulary, visible in the workbook itself |
| **Legend** | how to read it, the rule ladder, the known limits | the workbook has to survive being forwarded without you |
| **Coverage** | every measured number, with its target | lets a sceptic audit the claims from inside the file |

Sheet 1 has frozen panes and an AutoFilter. A consultant's whole workflow is: filter my
column to `X`, sort by `loc_total` or `inbound_refs`, read `description` and `evidence`.

Columns that carry the most weight in practice:

- **`role`** — a T-Code, an orphan class and a parameterised transaction need completely
  different conversations.
- **`inbound_refs`** — for "(no entry point)" rows this is the whole story. `0` means
  nothing in the repository references it: a dead-code candidate. `> 0` means it *is*
  used, just only by other code that itself has no entry point (mutually-referencing
  class pairs; OData MPC/DPC classes whose service registration points at a standard
  proxy, so the entry point exists in SAP but cannot be linked from source). Those are
  **not** dead code, and saying so in the legend prevents a wasted week.
- **`confidence`** — HIGH means an authoritative signal (package, resolved entry program,
  enhanced standard object). MEDIUM means a naming convention. LOW means inferred.
- **`evidence`** — the clause list. This is what makes a disagreement a conversation
  rather than an argument.
- **`proposed_modules`** — evidence for an area with no column yet.

## Handing it over

Say four things, in this order:

1. **A tick means "you have a stake", not "you own it".** Multi-ticked rows are correct
   and deliberate; both teams should look.
2. **A row is a whole nesting**, not one object. Children are on the Unit Members sheet.
3. **The limits are on the Legend sheet.** Read them before concluding something is
   missing.
4. **Corrections come back as edited tick cells** in this same workbook, and they are
   permanent.

## The correction loop

```
python <skill>/scripts/modindex.py overrides --ingest <returned>.xlsx --reviewer <name>
```

Each changed tick becomes an `ADD` / `REMOVE` row in `overrides/module-overrides.csv`,
with reviewer and date. That file is the **only** thing the build never writes, and it is
always applied last — so a correction cannot be destroyed by a rebuild, a rule change,
or a re-scan. That guarantee is what makes a consultant willing to review thousands of
rows.

Ingest refuses to run when the returned workbook's rows do not line up with the baseline
snapshot, because that is what happens when someone sorts or filters and saves — and
silently ingesting a re-sorted sheet would scramble every correction. If it refuses,
re-export a fresh workbook and ask for tick edits only.

Actions available by hand in the override file: `ADD`, `REMOVE`, `CROSS`, `ROLE`,
`EXCLUDE`. Always fill in `reason` — it is what makes the correction auditable a year
later, and what tells you whether to fix the rule instead.

Two counters in the apply output are worth reading every run:

- **stale** — the override names a root that no longer exists as a unit. Usually the
  object was renamed, deleted, or is now folded into another unit. Retire it.
- **redundant** — the machine now agrees with the correction on its own. That means a
  rule improved; retire the override so the rule stays the source of truth.

## Reviewing it yourself before you send it

The `spotcheck_sample.csv` protocol, honestly executed, is the difference between a
workbook that survives its first review meeting and one that does not:

1. Open the object in the source tree.
2. Read its description and first ~30 lines.
3. **Name the module from your own knowledge — before reading the `evidence` column.**
4. Compare, and record `CORRECT` / `INCOMPLETE` / `WRONG`.

Acceptance: ≥90% correct in the HIGH strata, ≥75% MEDIUM, ≥60% LOW. A `WRONG` verdict is
a defect in a rule table — fix the rule and re-run; do not paper over it with an
override. The sample is drawn with a fixed seed, so the same sample can be re-audited
after a fix.

## Things not to put in the deliverable

- **Revision history or changelog notes.** A limit that no longer exists is not a limit.
  A workbook that explains what used to be wrong invites doubt about what still is.
- **Hardcoded counts in prose.** Everything is computed; keep it that way.
- **Absolute paths, machine names, or customer-identifying strings** if the report is
  anonymised — check the surrounding report's convention before adding a `source_file`
  style column.
- **A passing grade you did not earn.** No held-out source means the appendix says rule
  R1 is unvalidated. That sentence costs nothing and buys all the credibility of the
  rest.
