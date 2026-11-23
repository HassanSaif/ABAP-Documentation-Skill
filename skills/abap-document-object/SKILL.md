---
name: abap-document-object
description: Use this skill to produce or refresh the per-object drill-down for a SINGLE ABAP object (T-Code, OData service, SICF node, BAdI implementation, class, function group, orphan program, or CDS view) without going through the full repo-wide inventory and coverage-audit dance. Triggers on requests like "document T-Code ZXX01", "drill ZCL_FOO_BAR", "write the doc for OData service ZBAR_SRV", "create the per-object doc for BAdI impl ZBADI_X", "refresh the doc for ZPROG_NAME". Apply the 11-section template from the `abap-documentation` skill, write the file to `docs/{area}/{NAME}.md`, and update reciprocal cross-references on linked docs. Do NOT use this skill for repo-wide passes, coverage audits, or "document this whole repo" requests — use `abap-documentation` for those.
metadata:
  version: "2.1.1"
---

# ABAP Document-Object Skill (one-shot, single object)

The companion skill to `abap-documentation`. Use this when the user wants the drill-down for **one** named object, not a whole pass.

> If the `abap-documentation` skill is installed in this environment, use its embedded 11-section template and `module-vocab.md` directly. If it is NOT available (e.g. only this skill was uploaded), the numbered section list in step 4 below is the binding contract — every section must appear as its own numbered `##` header, using `_Not applicable — <reason>_` where a section doesn't apply.

> **Don't run** the full Phase-1 inventory script or rebuild the coverage matrix. Touch only what's needed for the named object and its reciprocal cross-references.

---

<!-- hard-rules:start — keep this block identical in abap-documentation and abap-document-object; tools/package_skills.py fails if they differ -->
## Drill-down hard rules — binding on every drill

These rules apply to every drill: a repo-wide pass, a single object, or a sub-agent batch. They **override**
anything else in this skill, in the repo's own docs, or in a sub-agent prompt that seems to allow otherwise. If a
rule cannot be followed, **stop and tell the user** — never work around it. The rest of this skill explains *why*
and *how*; this block is *what is not negotiable*.

### A. Scope and depth — what gets drilled

1. **Drill custom code only, all the way down.** Open the source and document the behaviour of every object in
   the customer namespaces `Z*` / `Y*` and in any partner / add-on namespace (e.g. `/DBE/`, `/ABC/`) recorded under
   **"Namespaces in scope"** in `docs/_methodology.md`. Follow every such callee recursively until the tree is
   closed — there is no depth limit for custom code. A `/XXX/` namespace that is not yet recorded: **ask the user**
   whether it is in scope, then record the answer there before drilling it.
2. **Never drill SAP standard — look it up and fold it in.** A standard object reached from custom code (BAPI,
   function module, class, program, transaction, BAdI definition, table, CDS view) gets **no doc of its own and is
   not recursed into**. Instead:
   - **a.** Check `docs/_index/sap_standard.md` first. If the object is not there, run a **quick web search** for
     what it *does* — prefer help.sap.com, SAP Community and SAP-Note summaries, then established SAP reference
     sites. One or two searches, not research.
   - **b.** Write a one-to-two-line summary **inside the calling custom object's doc** — in §6 (calls) or §5
     (tables) — stating what the standard object does **and the role it plays in this flow**, with the source URL.
   - **c.** Append the lookup to `docs/_index/sap_standard.md` (`| Name | Type | What it does | Source | Date |`) so
     the next drill and every team member reuse it instead of searching again.
   - **d.** No web access, or nothing reliable found: write what you know, mark it **`(unverified)`**, and list it
     in §11. Never present an unverified description of SAP standard as fact.
3. **A branch stops only at:** SAP standard (rule 2); a dynamic call whose target cannot be resolved from source
   (state it as a limit in §11); or an object absent from the export (say *"not in the repository export"* in
   §11). Stopping anywhere else is a gap, not a decision.

### B. Evidence — what may be written

4. **No claim without source.** Every statement about behaviour — what the code does, which tables it reads or
   writes, which checks it runs — must come from a source file **opened in this session** and cite `file:line`.
   Metadata XML alone is not behaviour. Anything drawn from names, short texts, comments, package names or memory
   goes in §11, labelled as inference. Never write a doc from memory of an earlier read or from a sub-agent's
   summary. A listed source that cannot be found is **reported**, never improvised around.
5. **Modules come from evidence, not from a list.** `module-vocab.md` (and any module-index config) is guidance,
   **not a closed set**. Place the object in §2 from what the code does — tables it **writes** first, then tables
   read, BAPIs / FMs called, transactions used — and name whichever module that evidence points to, **including
   modules not on any list** (EWM, TM, GTS, PS, QM, HCM, Treasury, Real Estate, IS-* industry solutions, …). Where
   the evidence disagrees with the object's name or package, the evidence wins and the disagreement goes in §9.
6. **Template is fixed.** All 11 sections, each its own numbered `##` header; a section that does not apply says
   `_Not applicable — <reason>_`. A doc is not written until `check_template_compliance.py --strict` passes on it.

### C. Write safety — what may be changed

7. **Read-only outside `docs/`.** Never edit, reformat, rename, move or delete ABAP source, abapGit XML, or any other
   file outside `docs/` (and `docs_docx/` when DOCX rendering is requested). Defects are **documented in §9, never
   fixed** — if the user seems to want a fix, ask first; that is a different task.
8. **Never overwrite a doc.** Before writing, test the exact target path (`test -e docs/<area>/<NAME>.md`). If it
   exists, **read it in full and extend it** as a marked addendum — never replace it. Never move or rename an
   existing doc; report a misfiled one instead.
9. **No commit or push without the user's explicit OK.** Never `git commit`, `git push`, create a branch or open a
   PR unless the user asked for it in this session. Wherever this skill says "commit per family / per phase", it
   means *propose* the commit and wait for approval.
<!-- hard-rules:end -->

---

## Workflow

### 1. Identify the object type from the name

| Name pattern | Likely type | Lookup |
|---|---|---|
| 4–20 chars, `Z*` or `Y*`, no underscore-suffix conventions | Could be T-Code, program, or class — disambiguate by searching | Glob `**/src/*.tran.xml`, `**/src/*.prog.abap`, `**/src/*.clas.abap` |
| Ends in `_SRV` / `_CDS` / starts `ZCDP_` / `ZDMS_` | OData service | Glob `**/src/*.iwsv.xml` and `*.sicf.xml` |
| Starts `ZCL_*` / `ZIF_*` / `ZCX_*` | Class / interface | Glob `**/src/*.clas.abap` |
| Starts `Z_BADI_*` / `Z*_BADI_*` / matches enhancement convention | BAdI impl / Hook | Glob `**/src/*.enho.xml` |
| Looks like a function-group name (often shorter) | Function group | Glob `**/src/*.fugr.xml` |
| All-caps, contains `_VW` or similar CDS-naming | CDS view | Glob `**/src/*.ddls.asddls` |
| Ends `_B` / paired with a `.srvb.xml` | **RAP service binding** — a published OData endpoint, independent of SEGW | Glob `**/src/*.srvb.xml`; then `.srvd`, the projection CDS, and the `.bdef.asbdef` |
| Starts `ZBP_*`, or a `.bdef.asbdef` exists for the entity | **RAP behaviour implementation** | Read the `.bdef` first — it declares the write surface — then the handler class |
| A T-Code whose `*.tran.xml` has an **empty `<PGMNA>`** | **Parameter / query / variant transaction** — not a dead end | Read `<PARAM>`: `/*SM30 VIEWNAME=` → maintenance view (then `*.tobj.xml` + the maintenance function group); `REPORTTYPE=AQ` → an SAP Query (look for its `*.aqqu.xml` — abapGit does serialize queries); otherwise a parameter txn onto another T-Code |
| A 30-char hash filename | **hash-named satellite** (authorization defaults, launchpad config, MIME) | Never identify by filename — read `<DISPLAY_NAME>` / `<CONFIG_ID>` inside, and document it inside its host's doc |
| An e-mail template ID (often `ZZ1_*`, may contain spaces or hyphens) | **E-mail template** — a host without ABAP | Glob `**/src/*.smtg.xml` and match `<HEADER><ID>` (the filename is cut at the first space); see `abap-documentation` → "Host families without ABAP files" |
| A query name, or a T-Code whose `<PARAM>` has `REPORTTYPE=AQ` | **SAP query** — a host without ABAP | Glob `**/src/*.aqqu.xml` (`<user group> <query>.aqqu.xml`), then the InfoSet `*.aqsg.xml` |
| A BSP / UI5 app name, or an app id from the launchpad | **BSP / UI5 application** | `**/src/<app>.wapa.xml`, then `<app>.wapa.manifest.json` → `dataSources` names its OData service |
| A BOR object type, or a program with `SUBC = S` | **BOR object type** and its program | `**/src/*.sobj.xml`: `TOJTB-PARENT` (subtype vs stand-alone) and `TOJTB-PROGNAME` (the program) |

If ambiguous, ask the user one short clarifying question — don't guess.

### 2. Locate every source file for the object — by CONTENT, not by filename

**Run a repository-wide content search on the object name before anything else:**

```bash
grep -ril "<object_name>" <repo-root> --exclude-dir=docs
```

Then resolve each hit's identity from *inside* its XML. Use filename globs only to confirm what the content
search already found — never as the primary enumeration.

This matters because a logical object is routinely spread across many files in several object families, and
some members carry **no trace of the object in their filename**. Two recurring traps:

- **Hash-named families.** Authorization defaults (`*.sush.xml`), Web Dynpro / launchpad configs
  (`*.wdcc.xml`) and MIME objects are filed under an opaque hash. The friendly identity lives only inside —
  e.g. `<DISPLAY_NAME>` formatted `R3TR <TYPE> <NAME>`. A glob built from the object's name finds none of them.
- **`<name><whitespace><version>.<ext>`.** Several families (SICF, IWSV, IWMO, IWSG…) are written with the
  version or a hash appended after spaces. Split the filename stem on whitespace and take the first token;
  using the whole stem yields a key that matches nothing.

Also: objects can live in **nested sub-package folders** (`<pkg>/src/<subpkg>/...`), so walk recursively.

Files to expect, per object kind:

- Primary source (e.g. `ZCL_FOO.clas.abap`) plus its `.xml`.
- **T-Codes:** the `tran.xml`, the target program/screen, every include — **plus any launchpad/tile config that
  names the T-Code** (see step 2b).
- **SEGW OData:** the `.iwsv.xml`, `.iwsg.xml`, `.iwmo.xml`, `.iwom.xml`, `.iwpr.xml`, the DPC/DPC_EXT and
  MPC/MPC_EXT classes, the SICF node, any CDS view read — **and one `.sush.xml` per service and per service
  group**.
- **RAP service:** the `.srvb.xml` binding, `.srvd` definition, the projection and interface CDS views, the
  `.bdef.asbdef` behaviour definition, its `.ddlx.asddlxs` metadata extension, and the behaviour implementation
  class (`lhc_*` / `lsc_*` locals, or `ZBP_*`).
- **BAdI impls:** the `.enho.xml`, the impl class.
- **Function groups:** the FG `.xml` and every `.fugr.<fm>.abap` — **plus a `.sush.xml` (type `RF`) for each
  RFC-enabled FM**.

### 2b. Pull in the object's SATELLITES

Some object families never get their own document — they exist to say something *about another object*, and
their content belongs in **that object's** doc. Before writing, search for satellites pointing at your object
and fold what they say into the right section:

| Satellite family | Points at | Fold into |
|---|---|---|
| `*.sush.xml` — authorization defaults | an OData service, service group, or RFC-enabled FM | **§7** — which auth object is checked, and whether values are proposed |
| `*.wdcc.xml` — Web Dynpro / launchpad config | a **transaction code**, semantic object, catalog, tile | **§1** (how a user actually reaches it) and **§7** (catalog assignment may be the whole access control) |
| `*.ddlx.asddlxs` — CDS metadata extension | a CDS view | **§2 / §3** — it decides which fields a UI shows |
| `*.bdef.asbdef` — RAP behaviour definition | a CDS entity | **§4 / §5** — it declares the create/update/delete surface |
| `*.srvd`, `*.iwsg`, `*.iwmo`, `*.iwom`, `*.iwpr` | a service | **§3** — source-object table |
| `*.suso` / `*.susc` — custom auth objects & classes | nothing directly; they are the vocabulary | **§7** — cite the object a check *should* use |
| `*.tobj.xml` — maintenance object | a table maintained via generated maintenance | **§7** (`TDDAT-CCLASS`, the table authorization class — `&NC&` = non-classified) and **§4** (`TVIMF`: which form routines are wired, at which event) |
| SICF node with an OData handler | the OData service of the same name | the **service's** doc; the node gets only a routing stub |

**The direction matters.** A satellite names its host, but the host contains no reference back. So you cannot
find a T-Code's tile by reading the T-Code — you have to search the tile family for the T-Code's name. Do that
search explicitly; otherwise the reachability answer is silently missing from every doc you write.

### 2c. Original step — files already known

- Primary source (e.g. `ZCL_FOO.clas.abap`).
- Companion files (`.clas.xml`, `.iwsv.xml`, `.sicf.xml`).
- For T-Codes: the `tran.xml`, the target program/screen, every include the program uses.
- For OData: the `.iwsv.xml`, `.iwmo.xml`, the DPC class, the MPC class, the SICF node.
- For BAdI impls: the `.enho.xml`, the impl class.
- For function groups: the FG `.xml` and every `.fugr.<fm>.abap`.

### 2d. Include the files that are ABAP but are not named `*.abap`

When you enumerate the object's sources, remember that a `*.abap` glob is not the whole program:

- **Adobe form interfaces** (`*.sfpi.xml`) and **Smart Forms** (`*.ssfo.xml`) carry executable ABAP inside XML
  elements (`<FPCLINE>` and similar). Literals there are entity-escaped (`&apos;X&apos;`), so a grep written
  for source files finds nothing even when pointed at the right file.
- **Dynpro flow logic** lives in `*.prog.screen_NNNN.abap` — separate files from the module pool, and part of
  the behaviour for any dialog or screen-exit object.
- **Enhancement implementations** are `*.enho.<hash>.abap`; the hash means a glob on the object's name misses
  the code entirely.

If your object prints a form, drives a screen, or is an enhancement, say in the doc's footer which of these
file sets you read. A count or a "none found" claim is only meaningful with its file set named.

### 3. Apply the alias / hidden-name check

Even for a single object, run the relevant XML field check from `abap-documentation`'s "Hidden-name patterns" table. Cross-package splits are common; never assume the SICF and its OData impl are in the same package.

### 3b. Select the reading grammar

Before reading source, pick the reading order for the object's flavor from `abap-documentation/reading-grammars.md` (T-Code flavors — report/dialog/parameter/variant/OO; SEGW OData backwards-from-DPC_EXT; RAP via local handler classes; CDS annotation-first; enhancements target-context-first; OO classes public-interface-first). If the sibling skill isn't installed, the short version: classify the entry point from its metadata XML first, read upstream context before downstream detail, and in classic code grep for SUBMIT / CALL TRANSACTION / CALL CUSTOMER-FUNCTION / ENHANCEMENT-POINT / BAdI / VOFM / BTE side doors.

### 3c. Check whether the object is ALREADY documented — in EVERY area, not just the one you plan to use

Before writing a single line, search the whole docs tree for the object's name:

```bash
ls docs/*/ | grep -i "<NAME>"
grep -rl "<NAME>" docs/ --include=*.md | head
```

**Objects that belong to more than one family are filed under whichever family the first author
considered primary**, and that is frequently not the one you arrived from:

| The object you are drilling | May already be documented as |
|---|---|
| A RAP OData service (binding) | its **root CDS view**, under `cds/` |
| A CDS view with `@OData.publish` | an **OData service**, under `odata/` |
| A T-Code | its **target program**, under `programs/` — or the reverse |
| A form | the **program that prints it**, under `programs/` (they routinely share a name) |
| A function group | one of its **function modules**, or the T-Code that fronts it |
| A class | the **enhancement or SICF node** that binds it |

If a doc already exists, **update it** — add what your drill found as a clearly-marked addendum — and do
not create a second file. Two documents for one host object violate rule 6, split the reader's attention,
and will eventually disagree with each other. They also trip the duplicate-§4 content check once the two
descriptions of the same code converge.

If the existing doc is filed under a family you think is wrong, say so in your report and leave it where
it is. Moving a doc breaks every inbound link; that is the parent's call, not a side effect of your drill.

**Search the name you are about to WRITE, not the name you arrived from.** These are routinely different
objects, and searching the wrong one returns a clean result that means nothing. Arriving from a function
module and filing under its **function group**; arriving from a T-Code and filing under its **program**;
arriving from a class and filing under the **SICF node** — in every case the existence check must run on
the *filename you are about to create*. If the drill started at object A and the document will be called
B, **search for both**. The table above reads in both directions.

**Then make the check mechanical, because searching by name depends on choosing the right name.** The last
action before writing is to test the exact target path:

```bash
test -e docs/<area>/<NAME>.md && echo "EXISTS — READ IT IN FULL, DO NOT OVERWRITE" || echo "safe to create"
```

If it exists, **read the whole file and add to it**. Never write over a file you have not read. A `Write`
that reports *"updated"* rather than *"created"* has destroyed something, and in a repository with no git
history there is no undo.

This is not hypothetical. A large function-group document — several modules, findings anchored to it,
many inbound links — can be overwritten exactly this way: the drill arrives from a function module, runs
3c against the *module* name, finds nothing, and writes under the *group* name. **No
structural gate can catch this** — a valid 11-section document replacing a larger valid 11-section
document leaves compliance, validation, link checking and the orphan count all unchanged. The only
defences are the path test above and reading before writing. Recovery, when there is no version control,
means rebuilding from the register entries that cite the document plus the index descriptions that
summarise it — which works only because findings carry file:line detail, and is an argument for keeping
them that specific.

### 4. Read the source and write the doc

Use the **11-section template** from the `abap-documentation` skill verbatim:

1. End-User Story — **business value first**: the process step it carries, the decision it feeds, what it costs when it is wrong. A walkthrough of the screen and the output is not an End-User Story.
2. Functional View (use the module's cheat sheet from `abap-documentation/module-vocab.md` as guidance only — place the object from the tables it writes / reads and the APIs it calls, and name modules that have no cheat sheet; hard rule 5)
3. Technical Overview
4. Detailed Technical Spec
5. Database operations
6. External calls
7. Authorization
8. Customising / Configuration dependencies
9. Quirks / observations
10. Cross-references
11. Inferences & assumptions

Write to `docs/<area>/<NAME>.md`. Use the area folder that already exists in the repo (`tcodes/`, `programs/`, `classes/`, `function_groups/`, `enhancements/`, `cds/`, `odata/`, `sicf/`).

### 5. Update reciprocal cross-references

For every doc you link to in §10:
- Open it. Add a corresponding link back to the new doc in its §10.
- If the linked doc doesn't exist yet (e.g. you link to a class doc that hasn't been written), don't create it speculatively — but **flag it in your final response** so the user knows there's a dangling pointer that the next pass should fill.

### 6. Update the area README index and the `_index/<family>.md` table

If the area has a `README.md` index, add a row for the new doc in the appropriate section. If the area has a `_index/<family>.md` raw table that shows "documented?" status, flip the cell for this object.

Do NOT touch the repo-wide coverage matrix or `docs/_methodology.md` — that's the multi-object skill's job. Two exceptions, both from the hard rules: append new SAP-standard lookups to `docs/_index/sap_standard.md` (rule 2c), and record a newly confirmed partner namespace under "Namespaces in scope" in `docs/_methodology.md` (rule 1).

---

## What this skill does NOT do

- It does not regenerate `docs/_index/raw/*.tsv` — use the `abap-documentation` skill's full pass for that.
- It does not audit gap coverage repo-wide.
- It does not create speculative docs for objects mentioned in cross-references.
- It does not modify `docs/_methodology.md` (except the "Namespaces in scope" list — hard rule 1).
- It does not drill SAP-standard objects — it looks them up and folds a short summary into this object's doc (hard rule 2).
- It never edits anything outside `docs/`, and never commits or pushes without the user's OK (hard rules 7 and 9).

---

## When to escalate to the full `abap-documentation` skill

If during the single-object drill you realise:
- The repo's `docs/_index/raw/*.tsv` is stale (a referenced object isn't in it) — flag and offer to escalate.
- Multiple linked objects also lack docs — suggest the user run the full pass instead.
- You discover a hidden-alias pattern that affects many objects in the same family — flag in your final response, propose running the full pass to systematically fix the indexes.

---

## Output checklist (per single-object run)

- [ ] **`test -e docs/<area>/<NAME>.md` run against the exact filename about to be written** — not against
      the name the drill arrived from — and, if it existed, the file was **read in full and added to**
      rather than replaced. A `Write` reporting *"updated"* means a document was destroyed.
- [ ] New `.md` file written to the correct `docs/<area>/`.
- [ ] All 11 sections present (use "Not applicable — <reason>" rather than omitting).
- [ ] **Object set enumerated by content search**, not by filename glob — and the method stated in §10.
- [ ] **Satellites folded in** (step 2b): authorization defaults in §7, tile/launchpad config in §1 and §7,
      metadata extensions and behaviour definitions in §2–§5. A satellite is never a separate doc.
- [ ] §7 answers all three sources before concluding: `AUTHORITY-CHECK` in the ABAP, framework-level
      defaults in `*.sush.xml`, and any CDS `@AccessControl` annotation. **"No `AUTHORITY-CHECK` in the
      code" is not the same as "no authorization".**
- [ ] Source-object table in §3 enumerates every Z-source file touched.
- [ ] §10 cross-references both upstream callers and downstream callees.
- [ ] Reciprocal cross-references added to every linked existing doc.
- [ ] Area README index row added.
- [ ] For a maintenance-view transaction: §7 states the table authorization class from `*.tobj.xml`, and §4 distinguishes wired TMG event routines from unwired ones (checked *both* the `TVIMF` wiring and a `PERFORM` grep).
- [ ] For a generated function group: its members were enumerated, not assumed generated — hand-written function modules parked in a maintenance function group are documented.
- [ ] If the doc covers a FAMILY, its filename is a **real object name** from the inventory, not the stem the family shares — and every other member is named in the header line. Confirmed by the orphan count not rising.
- [ ] Any repository-wide count or "none found" claim in the doc names the **file set** it was measured
  over, and that set includes form / Smart Form XML and dynpro flow logic where relevant.
- [ ] Searched **every** `docs/<area>/` folder for the object name before writing, and updated an existing doc rather than creating a second one for the same host object.
- [ ] Every custom callee (Z / Y / in-scope partner namespace) was drilled or already documented; every SAP-standard
      callee is summarised in §5 / §6 with its source URL (or marked `(unverified)` and listed in §11), and new
      lookups were appended to `docs/_index/sap_standard.md`.
- [ ] Every behavioural claim cites `file:line` from a source opened this session; inferences sit in §11.
- [ ] Nothing outside `docs/` was modified; nothing was committed or pushed without the user's OK.
- [ ] Final response: any dangling cross-references (linked docs that don't exist yet) flagged for follow-up.
