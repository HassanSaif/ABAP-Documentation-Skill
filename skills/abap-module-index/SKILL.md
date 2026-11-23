---
name: abap-module-index
description: Use this skill to build a module index (module modularization map) for an SAP ABAP repository — a workbook with one row per entry-point unit (T-Code, OData service, SICF node, enhancement, CDS view, form, orphan program) and a tick per business module that has a stake in it, every tick carrying its evidence. The module list is open: SD, MM, FI, CO, WM, PP, QM, PM and custom buckets are only a starting point, and any module the source code proves is added. Triggers on requests like "which module owns this custom code", "map the custom estate to modules", "build the module index / module matrix", "split this Z-code between the functional teams", "who owns ZXX_FOO", "what does each package do". Works on any abapGit-serialized repo — flat export, package-per-folder, or a single abapGit repo — with no per-customer code changes. Do NOT use this skill to document individual objects in prose — use `abap-documentation` (repo-wide) or `abap-document-object` (single object) for that.
metadata:
  version: "1.8.1"
---

# ABAP Module Index

Build the artefact a functional team can actually work from: **one row per entry-point
unit, one tick per module with a stake in it, and the evidence behind every tick**.

A consultant's question is never "list the Z objects". It is *"which of these thousands
of objects is mine, and prove it."* This skill answers that, with a paper trail, a
reconciliation that cannot silently drop anything, and a correction channel that
survives every future rebuild.

The pipeline is in `scripts/modindex.py` (stdlib only; `openpyxl` for the workbook).
It carries no customer-specific code. Everything site-specific lives in one
`module-index.config.json`, and the skill proposes most of it from the repository.

---

## The five ideas that make the output trustworthy

**1. A row is a UNIT, not an object.** A unit is an entry point plus its entire
nesting: T-Code → program → includes → function modules → classes → forms. Children
get no row of their own; they are folded into the root and contribute their evidence to
it. This is what a consultant means by "one object" — and a list of units is reviewable
where the full object list, several times longer, is not.

**2. A tick means "this module has a stake", not "this module owns it".** Ticks are
additive and multi-valued. A class that splits a billing document is ticked in both the
sales and the accounting column, and both teams see it. `primary_module` carries the
single best-guess owner for pivot tables.

**2b. When two modules both have a stake, tick both — and the OWNER is the module
that has no transaction of its own for the job.** `IH09` displays the material master
from the Plant Maintenance side. Both MM and PM have a stake, so both tick; but MM
already owns `MM01/02/03` for that master, and PM has nothing else for it, so PM is the
owner and ranks first for `primary_module`. Reading it the other way loses the reason
the transaction exists at all. In `std_name_wrappers` the owner is simply listed first.

**3. The strongest evidence is what the code *does*, not what it is called.** The rule
authorities are measured, not assumed. Against held-out truth, *writing* a module's
standard tables is the most reliable signal, naming conventions come next, and *reading*
those tables or calling the module's change BAPIs trail well behind. So table writes are
authoritative and can name a module nothing else supports; reads and API calls stay inferred, because every module
reads and calls every other module all day. Where a naming rule and the tables both have
an opinion they must mostly agree — that gate is the one check that validates the rules
rather than the output, and its conflict list is the best triage list the build produces.
`scripts/measure_signals.py` measures each signal's accuracy and coverage on your own
estate — use those numbers, not anyone else's.

**4. Every OBJECT is accounted for, not just every unit.** Sheet 1 answers *which of
these units is mine?* The `Objects` sheet answers the question an owner asks instead:
*is every object in my estate accounted for?* They come apart, and the difference hides
real holes — objects can sit in Unattached under the line "attributed via its consumer"
while having no recorded consumer at all. Every scanned object now ends in
exactly one of three states, and a gate holds the third at zero: **ticked** with
evidence, **ruled out** because its only answer is a module the config declares out of
scope, or **unaccounted**. "There is nothing here" is an answer too — a four-line stub,
a SmartStyle, an unreferenced data element — and it is recorded as such rather than left
blank.

**5. The vocabulary is OPEN.** No estate's module list is known up front, and a closed
list fails silently — configure eight modules, index an estate that has ten, and the
missing two simply never appear. So any rule may name a module the config does not
contain: the hit lands in a **proposal register** with its evidence, the discovery
report asks for a decision, and AUTHORITATIVE evidence for an unmodelled area is a
**hard validation failure**. Nothing is dropped without a human writing down why.

---

## Workflow

Run this from the repository root. `python` means Python 3.9+.

### 1. Detect

```
python <skill>/scripts/modindex.py --root <repo> detect
```

Reports the layout (flat export / package-per-folder / abapGit repo), the per-package
export zips it can find, and any CSV that could serve as held-out validation. Point
`--root` at **one estate**, not a monorepo of unrelated repos.

If it reports a flat export with no zips, say so plainly to the user before going
further: abapGit strips `<DEVCLASS>` from every object file, so a flat tree contains no
package information at all, and rule R1 — the only authoritative signal — cannot fire.
The fix is one of: the per-package export zips, an object→package CSV, or accepting
name-based attribution with lower confidence.

### 2. Init

```
python <skill>/scripts/modindex.py --root <repo> init
```

Writes `module-index.config.json` with detected paths, package providers, the packages
it found (unmapped), and a held-out source if one was discovered. Do not hand-write
this file from scratch.

### 3. Scan and map packages

```
python <skill>/scripts/modindex.py run --to packages
```

`scan` is the only step that reads the source tree — budget minutes, not seconds, on a
synced drive (OneDrive/SharePoint/network share). Everything after it works from cached
TSVs, so rule tuning and re-rendering cost seconds.

### 4. Decide the vocabulary — this is the part that needs a human

```
python <skill>/scripts/modindex.py discover --adopt
```

`--adopt` writes only the package→module mappings where one module is unambiguously
ahead on hard evidence (name token, package short text). Everything else is parked
under `_packages_needing_a_decision`, a key the build ignores, so nothing takes effect
by accident.

Then read `<prefix>-discovery.md` and work through it **with the user**. Four kinds of
open item, each with exactly three honest outcomes — adopt, rule out with a reason, or
blacklist the token:

| Item | What it usually is | Your job |
|---|---|---|
| Unmapped package | a real module, or a technical/third-party package | map it, exclude it, or ask |
| Module named with no column | a module the estate has and the config lacks | adopt it, or rule it out **with a reason** — and see the warning below |
| Unmapped naming segment | a module, a cross-cutting bucket, **or an entity/plant/layer code** | the third kind MUST be blacklisted |
| Candidate family | a whole prefix owned by one area (handheld, e-invoicing, analytics) | add a family rule, or ignore |

Judgment that is genuinely yours, not the tool's:

- **Which modules this customer actually runs.** Decide it from the source — the
  standard tables the custom code *writes* — not from the default list in
  `sap-knowledge.json` or the example config, which are guidance only. Add every module
  the evidence shows (EWM, TM, GTS, PS, IS-* …) and narrow `modules.core` only with a
  measured reason. A column nobody owns is worse than no column; a module the code
  proves but the list lacks is worse still.
- **Cross-cutting buckets** (`X_EINV`, `X_TM`, `X_ANALYTICS`, `X_TECH`, …). Anything
  that is a *concern* rather than an SAP module belongs here, named `X_*` so it reads
  as visibly different from a core module.
- **Blacklisting look-alike segments.** This is the single highest-leverage decision in
  the whole config. Two-letter tokens in the module position are very often legal
  entities, plants, brands or architectural layers. Confirm what each one means from
  the objects' own short texts — never from the letters — and blacklist the ones that
  are not modules. An unfiltered token match smears one entity code across the estate.
- **Third-party code.** Vendored open source (abap2xlsx, abapGit, mocking frameworks)
  must never occupy rows. It is not custom business code and it drowns the real rows.
- **Ruling a module out is the one decision that can destroy an answer.** Every
  other decision redirects a tick; `not_modules` deletes it, and a unit whose *only*
  evidence was that module then ships with no tick and NONE confidence — which reads as
  "the tool had no idea" when the truth is "the tool had an answer and you removed the
  column". Write the reason as a **count you measured** ("zero objects touch any WM
  table"), never an impression ("no quality management at a retailer"), because the
  reason is what a later reader trusts instead of re-checking. The gate *a ruled-out
  module never silences a unit* fails the run if the decision costs a unit every tick it
  earned; small, real footprints belong in `modules.core` even at four units.
- **A held-out source.** Any SAP-side export with object and package columns — ATC
  results, a cloud-readiness check, a custom-code register. Without one, rule R1 is
  unvalidated, and the deliverable will say so in writing.
- **Any existing documentation in the repo.** Prose docs from an earlier pass that state
  a module per object are held-out truth written by a human reading source — often
  better evidence than a package column. Check the index against them
  (`references/method.md` §3b) — they routinely catch the worst misattributions in a
  build.

### 5. Run, then read the gates

```
python <skill>/scripts/modindex.py run
```

The validator prints PASS / WARN / FAIL and writes `<prefix>-validation.md`. **A FAIL
means do not ship the workbook.** Do not widen a threshold to make a gate pass; fix the
rule table and re-run. Every threshold in the config exists so the report can state
what it was measured against, not so it can be moved.

Re-tuning is cheap and safe:

```
python <skill>/scripts/modindex.py run --from attribute     # rules changed
python <skill>/scripts/modindex.py run --from units         # exclusions changed
```

The pipeline records which config sections each step depended on and refuses to start
mid-way on artefacts whose inputs have changed — it names the step to restart from.
Never reach for `--force` to get past that; it exists for the case where you have
already reasoned it through.

### 5b. Work the object-coverage list

`residual` writes `work/coverage_by_object.tsv` and the workbook's `Objects` sheet: one
row per scanned object, how it reached a module, on what evidence. The two gates on it
are *every scanned object is accounted for* (unaccounted must be zero) and *objects with
≥ 1 tick ≥ 95%*.

Anything still unaccounted after a run is a short, reviewable list — and each entry is
one of a small number of things, all of which have a right answer:

| What you see | What it usually means |
|---|---|
| a DDIC leaf with 0 consumers | genuinely unused custom dictionary — a finding, not a gap. It should be reaching R16 |
| an object whose only answer is a ruled-out module | check `modules.not_modules`; it should be landing in `ruled-out`, not here |
| a whole naming family at once | a missing family rule or a blacklisted segment that should not be |
| a variant of a standard transaction | the standard code is not in `std_name_wrappers` — add it, it is universal SAP knowledge |

Do not close the list by widening a threshold. Every one of these has a rule fix.

### 5c. Resolve the names you don't recognise

`discover` writes `work/unresolved_names.tsv` and a **Names to research** section in
`<prefix>-discovery.md`: every standard or custom name a unit *enters through* or an
enhancement *hangs off* that no rule could settle, ranked by how many units ride on it.
Work the top of that list, because one name can decide forty rows.

The procedure is fixed. Follow it in order:

| The name is… | Do this |
|---|---|
| a **`Z`/`Y` object** | it is in this repository. Find it, read the tables it reads and writes, classify from those. If it is genuinely absent it was never exported — say so as a stated limit |
| a **standard SAP name** | look it up. **What does it DO** — not which menu SAP files it under. Then add it to `std_name_wrappers` |
| a **transaction variant** | it names its T-Code in `<TCODE>` and its program in `<GUI_PROG>`. Resolve those two by the rules above; the **program** is the more informative, because a program name embeds its table (`RIMARA20` → MARA) where four characters cannot |
| a **generated name** (`GP00…`, `AQZZ…==`) | machine-generated, carries no meaning. `AQ` names decompose into user group + query — resolve to the query, or failing that its group |
| **still unsettled** | **ask the owner.** One answer usually settles a whole family, and a stated question is worth more than a quiet guess |

The same procedure applies to any row you distrust — a LOW or MEDIUM confidence tick, or
one whose evidence you don't believe: if it is custom, go to the tables; if it is
standard, go and look it up; if neither answers, ask.

Two lists exist so the answer sticks:

- `std_name_wrappers` — the name means a module. An entry may be `[pattern, module]` or
  `[pattern, [module, module]]`.
- `std_name_ignore` — the name means *nothing*. `SM30` maintains a table and the module
  belongs to the **table**; `SAPLSVAR` is the variant dialog, `SAPLSLVC_FULLSCREEN` the
  ALV grid. Leaving these out of both lists is the trap: they come back on the worklist
  every single run and train people to skip the report.

### 6. Read the content/name conflicts, then spot-check with domain knowledge

The validation report lists every unit where the naming rules and the standard tables
disagree. Read that list before anything else. A typical catch: a master-data family
ticking MM on the asset master, chart of accounts, vendor master and cost-centre master
— all FI or CO, as the tables say. Not every conflict is a defect (a BW
extractor reading MM tables is correctly ANALYTICS), so read each one.

Then:

`validate` writes a stratified, fixed-seed sample to `spotcheck_sample.csv`. Work
through it the honest way: open the object, read its description and first ~30 lines,
**name the module from your own knowledge BEFORE reading the evidence column**, then
compare. A `WRONG` verdict is a defect in a rule, not a row to override.

Acceptance: ≥90% correct in the HIGH strata, ≥75% MEDIUM, ≥60% LOW.

### 7. Deliver, and set up the correction loop

Hand over the workbook plus one sentence of instruction: *edit the tick cells and send
it back.* Then:

```
python <skill>/scripts/modindex.py overrides --ingest <returned>.xlsx --reviewer <name>
```

Each changed tick becomes a row in `overrides/module-overrides.csv` — the one file the
build never writes and always applies last. This is what lets you promise corrections
survive every future regeneration, which is what makes a consultant willing to review
thousands of rows.

---

## Non-negotiables

- **The module list is guidance, never a boundary.** No default list, example config or
  earlier config limits which modules may appear. Every module the source evidence points
  to gets a column, a bucket, or a ruled-out reason written as a measured count — and every
  module already in the config is double-checked against the tables the code actually
  writes before it is kept. When the evidence and the list disagree, the evidence wins.
- **Never hardcode a measured number into prose.** Every count in the legend and the
  narrative is computed from the pipeline's own stats files. A hardcoded figure goes
  stale the moment a package is added, in a document whose whole value is trust.
- **Never let the reconciliation identity slide.** `roots + folded members +
  unattached == every object scanned`. It is asserted, and a mismatch aborts the run.
- **Never report validation you do not have.** No held-out source means "NOT
  VALIDATED", never a pass.
- **State the limits in the deliverable itself.** Dynamic calls, config-driven form
  selection, parameterised T-Codes with no custom code, references to never-exported
  packages. A named limit is a finding; an unnamed one is a hole a consultant discovers
  on their own and stops trusting the rest.
- **A parameterised T-Code is customizing, not missing data.** Label it that way.
- **Corrections live outside the build.** Nowhere else survives a rebuild.
- **"Covered via its consumer" is a claim, not a category.** If an object has no
  recorded consumer, saying that is false. Check the count, not the label.
- **A ruled-out module is not an unknown.** They are different states and the deliverable
  must show them differently, or someone re-takes a decision that was already made.
- **When you cannot settle a name, ask — do not guess.** Custom name: go to the tables.
  Standard name: go and look up what it *does*. Neither answers: put the question to the
  owner. A LOW-confidence tick nobody can defend is worse than a stated question.
- **Run at least two regression estates before shipping a rule change.**
  `scripts/regress.py` takes `(root, config)` pairs and asserts the gate counts. Every rule in this skill was
  added or rejected on measured evidence, and a rule that improves one estate while
  smearing another is a rule that has not been measured yet.

---

## References — read the one you need

| File | Read it when |
|---|---|
| `references/method.md` | you need the unit model, the full rule ladder, the residual pass, the anti-smearing brakes, or how to diagnose bad attribution |
| `references/configuration.md` | you are writing or fixing `module-index.config.json`, or the layout/package source is unusual |
| `scripts/measure_signals.py` | you want the accuracy and coverage of each signal measured on THIS estate rather than quoted from another |
| `references/traps.md` | something extracted wrongly, or a rerun is not byte-identical. Every entry is a defect that shipped once |
| `references/deliverable.md` | you are handing the workbook to consultants, or running the correction round-trip |

`scripts/defaults/sap-knowledge.json` holds the universal SAP knowledge (standard
tables per module, BAdI spots, exit includes, object types, role labels). Extend it when
you learn something true of *any* SAP system; put anything true of *one customer* in
their config.
