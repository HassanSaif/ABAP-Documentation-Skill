---
name: abap-documentation
description: Use this skill for repo-wide SAP/ABAP documentation work on abapGit-serialized repositories — full passes producing per-object drill-downs across whole object families (T-Codes, OData services, SICF nodes, enhancements, classes, function groups, CDS views, orphan programs). Triggers on requests like "document this ABAP repo", "create docs for the Z* package", "audit the docs for missing objects", "run a documentation pass", "what's the documentation plan for this project". Apply the methodology end-to-end — inventory → alias-resolution audit → per-object drill-downs following the 11-section template → cross-references → coverage matrix. Output is markdown only (per-object `.md` files in `docs/{area}/`). Do NOT use this skill for a single named object ("document T-Code ZXX01", "drill ZCL_FOO_BAR") — use the companion skill `abap-document-object` for that.
metadata:
  version: "2.3.1"
---

# ABAP Documentation Skill

This skill governs how you produce documentation for SAP ABAP repositories serialized via abapGit (or comparable layouts). It encodes a methodology refined on large custom-ABAP repositories spanning T-Codes, classes, enhancements, SICF nodes, OData services, CDS views, forms and workflow.

Follow it for **any** documentation work in an ABAP repo, including initial passes, refresh passes, and gap audits.

---

## Execution environments

Resolve `$SKILL_DIR` (the folder containing this `SKILL.md`) once at the start of every pass; all script commands below reference it.

**Claude Code (local machine):** `$SKILL_DIR` is `~/.claude/skills/abap-documentation` (personal), `<project>/.claude/skills/abap-documentation` (project), or — when installed as the `abap-docs` plugin — `skills/abap-documentation` inside the plugin's install folder under `~/.claude/plugins/`. If unsure, find this file (`SKILL.md` next to `scripts/extract.py`) rather than guessing. The repo is a live git working copy — propose a commit per family or per phase, and commit only after the user's OK (hard rule 9). Cross-session memory (`feedback` / `project` / `reference`) is available.

**claude.ai / Cowork (ephemeral container):** the skill is mounted read-only; locate it by searching for this file (e.g. under `/mnt/skills/`). The user must upload the abapGit repo (zip) — extract it to a working directory and treat that as repo root. **Skip all git commit/push steps** (no repository access). Deliver results as a zip of the `docs/` tree via the outputs directory. Cross-session memory types are not available — record project-specific deviations in `docs/_methodology.md` instead (that file travels with the repo and is the canonical place for them in ALL environments). `pandoc` may be unavailable; if Phase 5 is requested and pandoc is missing, install it or fall back to a python-docx-based render and say so.

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

## Doc tiers — vocabulary

These tier names are used throughout this skill, the compliance script, and the reviewer prompt:

| Tier | What it is | 11-section? | Legitimate when |
|---|---|---|---|
| **Full v1** | Complete drill-down, all 11 sections populated from an actual source read | Yes | The end state for every substantive object |
| **compact** | Generator-emitted short-form doc (< 11 sections) | No | Never a final state — breadth placeholder only; must be upgraded via tree walks. Its presence blocks any "closed/complete" claim |
| **delta** | Documents only what changed vs. an existing Full v1 doc | No | Refresh passes on objects with small diffs |
| **thin** | Reduced doc for low-behaviour objects (e.g. a trivial wrapper) | No | Object genuinely has < 1 screen of behaviour; must say so explicitly |
| **stub** | Pointer/routing doc (e.g. SICF node fronting a Z OData service → points at the service doc) | No | Routing-only objects, produced same-pass (rule 10) |
| **index-only** | Row in `docs/_index/<family>.md`, no per-object file | n/a | Minor DDIC, auto-generated DPC/MPC, SAP-standard auto-activations (rule 9) |
| **partial** | A doc that *should* be Full v1 but is missing sections — a compliance failure, not a tier | — | Never. Phase 3.5 exists to eliminate these |
| **hollow** | All 11 headers present but content checks fail: empty section bodies, skeleton residue, off-topic body, or §4 duplicated across docs — the classic mid-run / parallel-sub-agent drift signature. A compliance failure, not a tier | — | Never. Caught deterministically by the compliance script (checks H1–H6) |

A doc's footer must declare its tier honestly (see reviewer prompt for footer examples).

---

## Philosophy — three-tier voice, one file per substantive object

Every per-object doc reads three ways:

1. **End-User Story** — **what is this object worth to the business, and what breaks without it — and who does what with it?** Both halves are mandatory: the value (the process step it carries, the decision it feeds, the cost of getting it wrong) **and** the human with their action (the dispatcher, the AP clerk, the integration partner — named, doing something specific). Value first, person second; the click-path is §2/§4 material, not this.
2. **Functional View** — what does the module consultant (SD/MM/FI/PM/etc.) care about — module placement, mechanism, equivalent SAP standard, customising hooks?
3. **Technical View** — what does the developer need — call chain, source-object table, line-by-line spec, database operations, external calls, authorization, quirks?

A doc that skips any of these tiers is incomplete. Don't produce aggregate prose; produce one `.md` per substantive object.

---

## The 11 methodology rules

1. **Index everything first.** Start with a comprehensive inventory of all objects in scope, grouped by type. Build a navigable index (`docs/_index/<area>.md`) — each entry must point at its per-object drill-down or be explicitly marked "index-only".

2. **Resolve hidden / aliased names BEFORE classifying scope.** AbapGit serializes some object families under SAP-generated identifiers; the friendly business name lives inside the XML. Always extract the logical name from the XML — never trust filenames alone. See the "Hidden-name patterns" section below for the field-by-field map.

3. **Drill the relations between objects.** For every substantive object follow the call chain: T-Code → program → class → BAdI → CDS → tables. Read the actual source (`*.clas.abap`, `*.prog.abap`, `*.ddls.asddls`) — don't infer behaviour from metadata XML alone. Document upstream callers and downstream callees on both ends.

4. **Understand the logic.** List signatures and field names, yes — but also capture quirks, hard-coded values, dead code, commented-out blocks, debug remnants, broken date arithmetic, security gaps, German comments. These go in the "Quirks / observations" section. Documentation that hides defects helps no one.

5. **Don't assume colocation by package.** A SICF node, its backing OData service, the DPC/MPC classes, and any helper FUGR may sit in different packages. Follow references across package boundaries.

6. **One `.md` file per substantive *host* object — and satellites are never their own file.** Object families
   divide into two kinds, and the distinction decides the whole shape of a pass:

   - **Host objects** get a document: T-Codes, programs, load-bearing classes, substantive function groups,
     enhancement implementations, CDS views, OData services (SEGW **and** RAP service bindings), bespoke SICF
     nodes, orphan programs — **and four families that carry no `*.abap` file of their own: e-mail templates
     (`*.smtg.xml`), SAP queries (`*.aqqu.xml`), BSP / UI5 applications (`*.wapa.xml`) and BOR object types
     (`*.sobj.xml`)**. See "Host families without ABAP files" below; leaving them out under-counts the estate
     with no error anywhere.
   - **Satellite objects** exist to say something *about a host*. Their content is folded into the host's
     document and they get **no file of their own** — but they must be **cited** in the host's doc, because they
     usually carry the answer to a section the host's own source cannot answer.

   **Canonical folder names:** `tcodes/`, `programs/`, `classes/`, `function_groups/`, `enhancements/`, `cds/`,
   `odata/`, `sicf/`. **Do not use `fugr/` for function-group docs** — the abapGit `.fugr.xml` extension is
   unrelated to the docs folder name, and the validator + index renderer both hardcode `function_groups/`.

   See **"Host and satellite families"** below for the mapping and — critically — for the *direction* problem:
   a satellite names its host, but the host never names the satellite, so satellites are only ever found by
   searching **from** the satellite family **back to** the host.

   **A family document must be filed under the name of a REAL object.** When one document covers several
   related objects — numbered siblings, forked generations, a composite and its members — it still has to be
   named after an object that exists in the inventory, never after the stem the family shares. A file named
   for a stem that no object carries becomes a permanent orphan: the validator reports *"exists but no TSV
   row"*, and the gap it was written to close stays open. Pick the member the family is reached through (the
   one behind the primary transaction, or the composite object if one exists) and name the file that, with
   every other member named in the header line so a search on any of them lands there. The orphan count is
   what distinguishes a safe stem from an unsafe one, and it costs one validator run to check.

   **One host object, one document — even when the object spans families.** A RAP service binding, its
   service definition, its behaviour definition and its root CDS view are *one* host; so are a T-Code and the
   program it exists to start. Put the document wherever the object's centre of gravity is, name the
   alternatives in that doc's title or quick-facts line so a search from any direction finds it, and never
   create a parallel file for the same object under a second area. Before creating any doc, search every area
   folder for the name.

7. **Every per-object doc follows the 11-section template** (see "Embedded template" below).

8. **READMEs in each `docs/<area>/` folder are pure indexes** — pointing at per-object drill-downs, not aggregating their content.

9. **Skip minor DDIC objects** — data elements, domains, search helps, table types, message classes. These are referenced where used (in the parent object's "Source-object table" and "Cross-references") but don't get their own files. Also skip auto-generated DPC/MPC base classes — they ride on their OData service doc.

10. **No deferred stubs.** If methodology calls for a URL-routing or pass-through stub (e.g., a SICF node fronting a Z OData service), produce the stub in the same pass. "Add later" notes become permanent gaps.

11. **Enumerate a composite object by CONTENT search, never by filename glob.** Several object types are not one
    file — they are one *logical* object scattered across many files and several abapGit families, and some members
    are filed under names that contain no trace of the object they belong to. A glob built from the object's name
    finds most of them and silently misses the rest.

    **Always run `grep -ril "<object_name>" <repo> --exclude-dir=docs` first**, then resolve each hit's identity
    from *inside* its XML. Use filename globs only to confirm what the content search already found, never as the
    primary enumeration. The difference is routinely two or three files, and the missed ones are disproportionately
    the metadata families (authorization defaults, service groups, model bindings) rather than the code — i.e.
    exactly the files that answer sections 7 and 8 of the template.

    A SEGW OData service, for example, is typically **9–12 files across 6–8 families in 2–3 packages**: the SICF
    node, `.iwsv`, `.iwsg`, `.iwmo`, `.iwom`, `.iwpr`, the DPC/DPC_EXT/MPC/MPC_EXT classes, any CDS view it reads,
    and one `.sush` authorization-default object per registered service **and** per service group. Document all of
    them as **one** `.md`, with the object set enumerated in section 3 and the enumeration method stated in
    section 10.

    See "Composite object families" below for the per-type member lists. (The typical failure: SICF nodes marked "stub if needed" are never followed up, and the gap outlives every later pass.)

---

## Workflow — four phases per pass

### Phase 1: Inventory (automated)

At the start of every pass — initial OR refresh — produce a fresh source-of-truth inventory before any drilling. Inventory is automated. The skill ships a Python harness at `scripts/extract.py` (alongside this `SKILL.md`).

Run it from the repo root:

```bash
python "$SKILL_DIR"/scripts/extract.py --repo-root . --output docs/_index/raw
```

(`$SKILL_DIR` = the folder containing this `SKILL.md` — see "Execution environments" above. Resolve it once at the start of the pass and reuse it for every script invocation. On Windows/Claude Code it is typically `%USERPROFILE%\.claude\skills\abap-documentation`.)

The harness is stdlib-only (no third-party deps), walks every `<package>/src/` folder, and emits one TSV per object family. **Critically**, for every family that hides its friendly name behind an SAP-generated identifier, the TSV has both columns populated (on-disk name AND logical name). At the end it prints a "hidden-alias report" enumerating every object whose disk-name differs from its logical-name.

For each object family, the scan captures **both** the on-disk filename AND every hidden friendly-name field from inside the XML (see "Hidden-name patterns" below).

**Before trusting the harness output, run the object-type census** (see "Host and satellite families" below) and confirm the extractor covers every object type actually present. A family the extractor does not know about produces no error — it simply never appears, and neither do the facts it carries.

If the repo already has `docs/_index/raw/*.tsv`, regenerate them — don't trust the snapshot. Compare new vs old; flag any objects added or removed since the last pass.

Output of Phase 1:
- `docs/_index/raw/<family>.tsv` — one row per object, all logical-name columns populated.
- `docs/_index/raw/summary.tsv` — counts per family.

Immediately after `extract.py`, render the human-navigable indexes:

```bash
python "$SKILL_DIR"/scripts/render_indices.py --repo-root . --index docs/_index/raw --output docs/_index
```

This produces `docs/_index/<family>.md` for every family, with both `on-disk-name` and `friendly-name` columns visible in the markdown table. Re-run any time the underlying TSVs change.

### Phase 2: Coverage audit

Compare inventory against existing per-object `.md` files in `docs/<area>/`. Produce a coverage matrix:

| Area | Source objects | Per-object .md exists | Gap (substantive) | Action this pass |

For each gap, classify:
- **Substantive** → needs per-object doc this pass.
- **Routing-only** → needs thin stub this pass (rule 10).
- **Auto-generated / minor DDIC** → index-only per rule 9.

This matrix goes into `docs/_methodology.md` (or `docs/COVERAGE.md`) and drives the pass.

### Phase 3: Per-object drill-down

There are **two orthogonal ordering axes** — pick one to structure the pass:

#### 3a. Family order (default for greenfield passes)

Work through the coverage matrix in family priority order:

1. Entry points first — T-Codes, then SICF nodes, then OData services.
2. Enhancements (BAdI / Hook / CLASENH implementations) — high behaviour density.
3. Load-bearing classes (action dispatchers, helper classes, BAdI impl classes, AMDP classes).
4. Substantive function groups (SM30-dialog FGs, action dispatchers, RFC-enabled FMs).
5. Orphan programs (background jobs, RFC APIs, print drivers, uploaders).
6. CDS views referenced from any of the above but not yet drilled.

Use family order when the repo has NO existing docs — you're building coverage breadth first.

#### 3b. Tree-walk order (default for deep-drill escalations after breadth coverage exists)

When breadth coverage is already achieved (compact-generated docs exist for every object), escalate to Full v1 tier via **tree walks** — one entry-point at a time, exhaustively:

1. **Pick a T-Code** (or other entry point — SICF node, OData service, RFC-enabled FM).
2. **Deep-drill its target program** to Full v1 tier.
3. **Follow every custom callee recursively** (Z / Y / in-scope partner namespace — hard rule 1) — for each downstream custom program / include / class / FM found in the source. SAP-standard callees are looked up and folded into the caller's doc, never drilled (hard rule 2):
   - If a Full v1 doc already exists, only update its reciprocal cross-references.
   - If a compact / delta / thin / stub doc exists, upgrade to the tier the code warrants.
   - If no doc exists, create one at the correct tier.
4. **For every Function Module found, walk into its function group** — write/upgrade the FG doc; the FMs fold into it. Then recurse on the FG's own outbound calls.
5. **Only mark the tree "closed"** when every transitive custom callee has a doc, every SAP-standard callee is summarised in its caller's doc, AND every reciprocal cross-reference is bidirectional (validator green).
6. **When entry-point trees are exhausted**, do standalone / orphan programs (Phase G of the coverage matrix — programs with no upstream entry point).
7. **After orphans**, do enhancements, SICF Z-nodes, OData Z-services, Web Dynpro components, AIF interfaces — in that order.

**Realistic capacity per session:** 1-3 T-Code trees, or one large-fan-in shared-code cluster.

**Token-budget rules (apply in every phase):**
- For source files > 2000 LOC, do NOT full-read: grep for structure first (`FORM|METHOD|FUNCTION|SELECT|UPDATE|INSERT|MODIFY|DELETE|CALL FUNCTION|AUTHORITY-CHECK|SUBMIT|BREAK-POINT`), then read only the routines that matter for §4.
- When context is running low mid-tree: STOP cleanly at a doc boundary. Update the coverage matrix in `docs/_methodology.md` with exactly where the walk stopped (last closed object + remaining callees), run Phase 3.5 on what was written, and report the checkpoint. Never emit a partial doc to "get further".
- Do not paste large source excerpts into docs — §4 describes behaviour with line-number references; it does not mirror the code.

**Anti-patterns for tree walks:**
- Do NOT dispatch parallel sub-agents to drill different objects in the same tree — token cost is ~5× inline, and reciprocal cross-references become race-prone.
- Do NOT drill a downstream callee before its upstream caller — the caller's context (why is this called?) informs the callee's End-User Story.
- Do NOT skip cross-reference updates between tree-walk steps. A doc with dangling "pending drill-down" links is only half done.

For each object, use the **embedded 11-section template** below. Read the actual source — `.clas.abap` / `.prog.abap` / `.ddls.asddls` / FM `.abap` files inside FUGR folders — not just the XML metadata.

**Before reading any source: select the reading grammar.** `reading-grammars.md` (sibling file) defines the deterministic reading order per entry-point flavor. Consult it at the start of every drill. The dispatch table:

| Entry point | Grammar | First file to open |
|---|---|---|
| T-Code (report txn) | Classic 1a: program → event blocks in runtime order → includes/FMs/classes, recurse | `*.tran.xml` (confirms flavor), then the program |
| T-Code (dialog txn) | Classic 1b: module pool + **dynpro PBO/PAI flow logic** | `*.tran.xml`, then flow logic + module includes |
| T-Code (parameter txn) | Classic 1c: the real object is the maintenance view/table + TMG events — no program chase | `*.tran.xml` |
| T-Code (variant txn) | Classic 1d: THIN doc pointing at target T-Code | `*.tran.xml` |
| T-Code (OO txn) | Classic 1e: straight to class.method | `*.tran.xml`, then the class |
| SEGW OData | Grammar 2: read **backwards from DPC_EXT redefinitions**; generated base classes are noise | `*.sicf.xml` → `*.iwsv.xml` → DPC_EXT |
| RAP service | Grammar 3: binding → definition → projection CDS → **BDEF (the write surface)** → local handler classes (`lhc_*`/`lsc_*`) or `ZBP_*` | `*.srvb.xml` |
| RAP behaviour | Read the `.bdef.asbdef` **first** — `create`/`update`/`delete`, `managed` vs `unmanaged`, `authorization master`. `unmanaged` means custom ABAP implements the writes, which is where the defects are | `*.bdef.asbdef` |
| CDS view | Grammar 4: annotations first, then view stack down to tables | `*.ddls.asddls` |
| Enhancement | Grammar 5: target spot's context BEFORE the impl code | `*.enho.xml` |
| Load-bearing class | Grammar 6: public interface → constructor → methods in dependency order | `*.clas.abap` |

In every classic drill, also grep for the **side doors** (SUBMIT, CALL TRANSACTION, CALL CUSTOMER-FUNCTION, ENHANCEMENT-POINT, BAdI calls, VOFM, BTE, `PERFORM ... IN PROGRAM`) — behaviour hiding there is a common cause of incomplete §4/§6 sections. Sub-agent dispatch prompts MUST name the applicable grammar per object.

### Phase 3.5: Compliance gate (mandatory)

After every drill session, generator run, or sub-agent batch that produces or modifies per-object docs:

1. Run the compliance script on the affected docs:
   ```bash
   python "$SKILL_DIR"/scripts/check_template_compliance.py --repo-root . --strict
   ```
2. If the script exits `0` (zero `partial` AND zero `hollow` docs — every substantive doc has all 11 headers with real, on-topic, non-duplicated content): proceed to Phase 4.
3. If the script exits `1` (any `partial` or `hollow` docs remain in the output): dispatch the compliance-reviewer agent per `$SKILL_DIR/reviewer_agent_prompt.md`. The reviewer either fixes the docs in-place or reports specific manual fixes required.
4. Do **NOT** proceed to Phase 4 with any `partial`-tier doc still in the session output. A doc is not "written" until it passes this gate.

**Two-stage gate rationale:** the compliance script is a deterministic check (fast, free) that catches both structural failures (merged / missing headers → `partial`) and content-drift failures (`hollow`, checks H1–H6: empty sections, template residue, off-topic body, filler §4, duplicated §4 across docs, meta-filler/title-echo text that talks about a section instead of documenting the object). Use `--paths <files-or-folder>` to gate a single sub-agent batch cheaply without re-auditing the whole repo. The reviewer agent is dispatched only when the script fails, and is responsible for content-level fixes (populating missing sections with real source-read content or marking `_Not applicable — <reason>_`). Never dispatch the agent as a routine post-write step for every doc — the script does that check for free.

### Phase 4: Cross-reference & validate

After each per-object doc is written:
- Update the **reciprocal** docs on the other end of every cross-reference (caller side AND callee side). A doc that links to a class must trigger an edit on the class doc to link back.
- Update the area README index to add the new entry.
- Update `docs/_methodology.md` coverage matrix.

Validate at end of pass — run the validator:

```bash
python "$SKILL_DIR"/scripts/validate.py --repo-root . [--strict]
```

It produces three reports:

1. **Coverage** — per family, lists in-scope objects that have docs vs gaps. Out-of-scope rows (e.g. SAP-standard auto-activations, DDIC) are excluded from the gap count automatically.
2. **Orphan docs** — `.md` files in `docs/<area>/` that have no corresponding TSV row. Usually means the doc references an outdated name OR the TSVs are stale (re-run `extract.py`).
3. **Broken links** — every relative markdown link is resolved against the filesystem.

With `--strict` the validator exits non-zero on any gap, orphan, or broken link — useful for CI or pre-commit hooks.

SICF nodes are in scope when their alias or handler class is in the Z namespace. If the repo publishes handlers from a partner / add-on namespace (e.g. `/DBE/`, `/DBME/`), add `--sicf-handler-namespace DBE --sicf-handler-namespace DBME` (write the namespace without slashes — Git Bash on Windows rewrites `/DBE/` into a file path; the script normalises either form) and record that choice in `docs/_methodology.md` so every later pass uses the same scope.

Manual checks still recommended at end of pass:
- Every TSV row maps to either a per-object `.md`, an explicit stub, or an "index-only" classification.
- Every cross-reference link round-trips (caller links to callee AND callee links back to caller).

### Phase 5: DOCX rendering (optional)

If the project hands off `.docx` files to non-technical stakeholders (PMs, business analysts, auditors who don't read GitHub), render every markdown file to a parallel DOCX tree via pandoc:

```bash
python "$SKILL_DIR"/scripts/render_docx.py --repo-root . --docs docs --out docs_docx
```

- Mirrors the `docs/` folder structure into `docs_docx/` (`.md` → `.docx`).
- Incremental — skips files whose `.docx` is already newer than the source `.md`.
- `--force` re-renders everything.
- Requires `pandoc` on PATH. Install from https://pandoc.org/installing.html. Tested with pandoc 3.9+ on Windows/macOS/Linux.

When to run Phase 5:
- After every per-object doc is written or modified (incremental mode handles this — re-run cheaply).
- Before any handoff to non-technical reviewers.
- After bulk methodology edits (`_methodology.md`, `MASTER_INDEX.md`, area READMEs) so the DOCX tree stays in sync.

When **not** to run Phase 5:
- During the per-object drill-down phase itself — wait until docs stabilise, then bulk-render at the end.
- If the project lives entirely in GitHub / GitLab and stakeholders read the rendered markdown directly. DOCX is dead weight in that case.

Commit the DOCX tree alongside the markdown tree if downstream consumers depend on it (typical for client deliverables — non-technical reviewers can `git pull` and open `.docx` without needing pandoc). Add `docs_docx/` to `.gitignore` only if every consumer of the docs has pandoc and can render on demand.

---

## Executable ABAP lives outside `*.abap` files - every sweep must say which files it read

A defect sweep that globs `*.abap` silently skips real, running code. abapGit serializes several object
families as XML with the ABAP **inside** an element, where no source-file glob will ever see it:

| Family | File | Where the ABAP hides |
|---|---|---|
| Adobe form **interface** | `*.sfpi.xml` | `<FPCLINE>` elements - the interface's initialization/code section |
| Adobe form | `*.sfpf.xml` | code nodes in the form hierarchy (plus a `.xdp` layout, which is not ABAP) |
| Smart Form | `*.ssfo.xml` | program-line nodes |
| Enhancement implementations | `*.enho.<hash>.abap` | a real `.abap` file, but the **hash filename** means a glob on the object's name misses it |
| Dynpro flow logic | `*.prog.screen_NNNN.abap` | module calls and `FIELD`/`CHAIN` statements |
| Table maintenance events | `*.tobj.xml` `TVIMF` | names a form routine that lives in the generated FG |

The consequence is not theoretical: form interfaces routinely carry `BREAK-POINT` statements and hard-coded
`SY-UNAME` tests that run every time a document prints, and an `*.abap`-only scan reports zero of them.

**Rule: whenever you state a repository-wide count, state the file set it was measured over.** "187 occurrences"
is not a finding; "187 occurrences in `*.abap`, which excludes the form XML" is. If a later sweep widens the file
set, the earlier number is not wrong - it was scoped - but only if the scope was written down.

A practical sweep set for this kind of measurement:

```bash
# ABAP that a *.abap glob misses
find . -name "*.sfpi.xml" -o -name "*.ssfo.xml" -o -name "*.sfpf.xml"
# strip the XML wrapper before matching, or matches land on entity-escaped text
#   <FPCLINE>if sy-uname eq &apos;NAME&apos; .</FPCLINE>
```

Note the entity escaping: a literal inside XML-serialized ABAP is `&apos;NAME&apos;`, not `'NAME'`, so a grep
written for source files matches nothing even when pointed at the right file.

## Hidden-name patterns — extract these from inside the XML

Build a `disk-name → logical-name` map before classifying scope. The skill harness does this automatically; here's the field map it uses:

| Object family | File glob | On-disk source | Logical name field(s) inside XML | Notes |
|---|---|---|---|---|
| Transaction codes | `*.tran.xml` | `<TCODE>` | `<PGMNA>`, **`<PARAM>` (TSTCP)** | A T-Code with an empty `<PGMNA>` is **not** a dead end — the real target is encoded in `<PARAM>`. See "Classifying a parameter transaction" below. |
| SICF nodes | `*.sicf.xml` | `<ICF_NAME>` (often `DS41*`) | `<ICFALTNME>` | Alias is what URLs use via Gateway alias resolution. Decisions about "bespoke vs auto-activation" must use the alias, not the filename. |
| OData services (definition) | `*.iwsv.xml` | filename root | `<EXTERNAL_NAME>` / `<TECH_SERVICE_NAME>` | Filename usually matches; capture both. |
| OData service groups | `*.iwsg.xml` | filename root | `<BEP_SVC_TECHNICAL_NAME>` / `<BEP_SVC_SERVICE_NAME>` | High-cardinality (often hundreds); group by `BEP_SVC_SERVICE_NAME`. |
| OData model definitions | `*.iwmo.xml` | filename root | `<MODEL_NAME>` / `<EXTERNAL_NAME>` | |
| OData model assignments | `*.iwom.xml` | filename root | `<MODEL_IDENTIFIER>` + `<EXTERNAL_NAME>` + `<SAP_SYSTEM>` | `EXTERNAL_NAME` strips `_0001_BE` suffix — use it as the friendly name. |
| OData vocabulary bindings | `*.iwvb.xml` | filename root | `<ANNO_TECH_NAME>` + `<SERV_TECH_NAME>` | `_VAN` suffix on annotation name is internal; the service name is what consumers reason about. |
| Enhancements | `*.enho.xml` | `ENH_NAME` (matches filename) | `<ENH_BADI>` / `<ENH_HOOK>` / `<TGTNAME>` | The hidden field is the **target** spot — what the impl extends. Document both. |
| Classes | `*.clas.abap` + `*.clas.xml` | class name (matches filename) | `<CLSNAME>` — usually matches | DPC/MPC base classes (auto-gen by Gateway) skip per-object docs; they ride on their OData service doc. |
| Function groups | `*.fugr.xml` | FG name | per-FM: search `*.fugr.<fm>.abap` for `REMOTE-ENABLED` to flag RFC FMs | RFC-enabled FMs are external-API touch points and bump the FG into "substantive". |
| Programs | `*.prog.abap` | program name | `<DESCRIPT>` in `*.prog.xml` — descriptive text | |
| CDS views | `*.ddls.asddls` | view name | `@EndUserText.label` annotation | |
| **Authorization defaults (SU22/SU24)** | **`*.sush.xml`** | **an opaque 30-char hash** — the filename carries *no* hint of what it guards | **`<DISPLAY_NAME>`**, formatted `R3TR <TYPE> <NAME>` (e.g. `R3TR IWSV <service>`, `R3TR IWSG <group>`, or a bare FM name for type `RF`) | **The single most security-relevant family in a repo, and the easiest to miss.** Each object records which authorization objects guard an externally-callable object: `<USOBX>/<OBJECT>` names the auth object (`S_SERVICE`, `S_RFC`, `S_START`), `<OKFLAG>` = `X` means *checked*, and `<PR_TEXT>` = `No` means **no default values are proposed to role maintenance** — the check is enforced but role builders get an empty proposal, which is where blanket grants come from. Found only by content search (rule 11). Many extractors omit this family entirely — verify it is in your inventory before trusting any "no authorization check" statement. |
| **E-mail templates** | `*.smtg.xml` | filename **truncated at the first space** | **`<HEADER><ID>`** — may contain **spaces and hyphens** (`ZZ1_PO APPROVAL`, `ZZ1_XX-YY_APPROVED_CONTRACT`); `<CDS_VIEW>` = placeholder data source; `<PARENT_ID>` = SAP template it was copied from | Key templates by `<ID>`, never by filename. A coverage tool that tokenises names on `[A-Z0-9_/]` cannot see these IDs — give declarations (`**Covers:**`) a parser that accepts inner spaces and hyphens. |
| **SAP queries** | `*.aqqu.xml` | **`<user group><spaces><query>`** | `AQGQCAT`: `<NUM>` = user group, `<QNUM>` = query, `<CLAS>` = InfoSet; title = `AQGTQ-TEXT` where `HEAD = X` | The **last** whitespace token of the stem is the query, the first the user group. InfoSets (`*.aqsg.xml`) and user groups (`*.aqbg.xml`) are its satellites. |
| **BSP / UI5 applications** | `*.wapa.xml` + one sibling per page, `<app>.wapa.<page>` | `<APPLNAME>` | `<APPLCLAS>` (`/UI5/CL_UI5_BSP_APPLICATION` = deployed UI5 app); **`<app>.wapa.manifest.json`**: `sap.app.id` and `dataSources[*].uri` — the OData service the app calls | The manifest is the only file that links a front end to its back-end service. Read it, then document the app in (or beside) that service's document. |
| **BOR object types** | `*.sobj.xml` (+ program `*.prog.xml`, `SUBC = S`) | object type | `TOJTB`: **`<PARENT>`** (supertype — empty means stand-alone), `<PROGNAME>`, `<KEY_CONVERTER>`; `SWOTDV-VERBTYPE` M/A/E/K = method/attribute/event/key | `PARENT` decides everything: a **subtype** inherits SAP's implementation and can be a delegation target; a **stand-alone** Z type has its own program, often a verbatim **copy** of SAP's (SAP note markers, German comments) that SAP corrections no longer reach. The program's name usually differs from the type (`ZBUS2078` → `ZZBUS2078`). |

**Filename forms that break naive parsing.** abapGit does not always write `<name>.<ext>`:

- Some families use **`<name><whitespace><version-or-hash>.<ext>`** — e.g. `myservice                     0001.iwsv.xml`,
  `mynode 13f9712dd22141245452904ed.sicf.xml`. Deriving the object name requires splitting the stem on whitespace
  and taking the first token; using the whole stem yields a key that matches nothing and makes a correct index look
  empty.
- Some families use a **pure hash** with the real name only inside the XML (`*.sush.xml`, above).
- Objects can be filed in **nested sub-package folders** — `<pkg>/src/<subpkg>/...`, not only `<pkg>/src/`. Walk
  recursively (`os.walk`, `find`), never a single-level listing, or objects vanish from counts with no error.

**Repeated tag names.** A tag can be used as *both* a row wrapper and a field inside that row — SICF's handler
table is the canonical case:

```xml
<ICFHANDLER_TABLE>
 <ICFHANDLER>                                   <!-- row wrapper -->
  <ICFORDER>01</ICFORDER>
  <ICFHANDLER>CL_SOME_HANDLER</ICFHANDLER>      <!-- the actual field -->
 </ICFHANDLER>
</ICFHANDLER_TABLE>
```

A non-greedy regex `<TAG>(.*?)</TAG>` matches wrapper-open to field-close and returns a block of XML. Parse the
tree, or match only the leaf form `<TAG>([^<>]+)</TAG>`. **Anything stored as a table must be read as a table** —
taking "the" value yields one entry and silently discards the rest.

**Two complementary cross-cutting checks:**

- **Cross-package splits:** A SICF node may be in package A while its OData impl is in package B. Never assume colocation. Grep references both upstream and downstream.
- **Dead code:** A registered object with an empty implementation (e.g. an empty DPC class behind an activated SICF node) is *not* "not yet documented" — it is dead code and must be documented as such (flagged in Quirks).

---

## Host and satellite families

A satellite family points at a host object and is documented *inside that host's* `.md`. Getting this wrong
produces two failures at once: a pile of meaningless one-line documents, and host documents missing the very
facts a reviewer needs.

| Satellite family | Points at (host) | Section of the host's doc it belongs in | Why it is load-bearing |
|---|---|---|---|
| Authorization defaults (`*.sush.xml`) | an OData service, a service group, an RFC-enabled FM | **§7 Authorization** | Declares the framework-level check (e.g. a service-start authorization object) that the ABAP never mentions. Also records whether **any default values are proposed** — a check with no proposal is enforced but gives role maintenance nothing, the usual route to a blanket grant |
| Launchpad / Web Dynpro configuration (`*.wdcc.xml`) | a **transaction code**, semantic object, catalog, tile | **§1 End-User Story** and **§7** | The real answer to *"how does a user reach this?"*. Where a tile exists, **catalog assignment may be the entire access-control surface** |
| CDS metadata extension (`*.ddlx.asddlxs`) | a CDS view | **§2 / §3** | Decides which fields a UI actually shows; a view's doc is incomplete without it |
| RAP behaviour definition (`*.bdef.asbdef`) | a CDS entity | **§4 / §5** | Declares the **write** surface — `create` / `update` / `delete`, managed vs unmanaged, and who owns the authorization |
| RAP service definition (`*.srvd`) | a service binding | **§3** | Which entities the binding exposes |
| OData plumbing (`*.iwsg`, `*.iwmo`, `*.iwom`, `*.iwvb`, `*.iwpr`) | an OData service | **§3** source-object table | Registration and model wiring; individually inert, collectively the proof the service is real |
| SICF node whose handler is a standard OData/Gateway class | the service of the same name | the **service's** doc | The node is routing only; it gets a stub (rule 10), not an analysis |
| Custom authorization objects / classes (`*.suso`, `*.susc`) | nothing directly — they are the *vocabulary* | **§7** | Tells you which object a check *should* use. Without this family you cannot tell whether "no check" means "no control exists" or "the control exists and was not used" |
| MIME objects, message/email templates | the app or process that renders them | **§6 / §8** | |
| Minor DDIC (`*.ttyp`, `*.dtel`, `*.doma`, `*.shlp`) | wherever used | §3 / §8 | Rule 9 — index-only |
| Generated table-maintenance function group (`TABLEFRAME_<tab>` / `TABLEPROC_<tab>`) + its `*.tobj.xml` | the table — and through it, the code that **reads** the table | §8 of the reader's doc (or the transaction's doc if one exists) | One paragraph: key and value fields, delivery class, client field, authorization class, wired events, transaction or `SM30` only. **Find readers with comments stripped** — a commented `SELECT` is not a reader. A table nothing reads gets a shared "unread configuration" doc, not one doc per table |

### Host families without ABAP files — count them, document them

Four families are hosts in their own right although none of them is a `*.abap` file. A status or coverage
model that counts only code families will miss them silently — they surface only in an object-type census or a
content inventory. Give each a status area and a document (a catalogue document per family is fine when the
members are configuration-like and similar):

| Family | What it is worth documenting | Typical home | Satellites to fold in |
|---|---|---|---|
| **E-mail templates** (`*.smtg.xml`) | Which process sends it (derive from `<PARENT_ID>` and the workflow / notification that names it), subject and body placeholders, the CDS data source, **every hyperlink** — hard-coded system hosts (a development system in a production template) are a recurring finding | one catalogue document per process family, e.g. `workflow/EMAIL_TEMPLATES.md`, templates declared on its `**Covers:**` line by full ID | — |
| **SAP queries** (`*.aqqu.xml`) | The InfoSet's tables and joins, selection fields, output fields, the transaction that launches it (`REPORTTYPE=AQ` in a `*.tran.xml` `<PARAM>`); no `AUTHORITY-CHECK` exists — §7 is the user-group assignment plus the InfoSet's authorization group | `queries/<QUERY>.md`, one per InfoSet family | InfoSet `*.aqsg.xml`, user group `*.aqbg.xml` |
| **BSP / UI5 applications** (`*.wapa.xml`) | The app id, the OData service(s) from `manifest.json`, the launchpad target mapping that reaches it (`*.wdcc.xml`) | the **back-end service's** document (the app is that service's UI) — or its own document when it is not UI5 | page files `<app>.wapa.*`, MIME (`*.smim.xml`), the SICF node `/sap/bc/bsp/sap/<app>/` |
| **BOR object types** (`*.sobj.xml`) | Subtype or stand-alone (`TOJTB-PARENT`); methods, attributes, events; the program; who uses it (workflow tasks `*.pdts.xml`, classes, event linkages); for a copy of an SAP type, say so and that SAP corrections no longer reach it | the document of the class or process that uses it, or `programs/<BOR program>.md` | the BOR program (`SUBC = S`), workflow tasks bound to it |

**Coverage-tool consequences.** Template IDs contain spaces and hyphens; query names are the *last* token of
the filename; a BOR type's program has a different name from the type. Normalise all three from file content
before matching them against documents.

### Classes are usually satellites of another host — place them before writing

Most open classes are **not** their own host. Classify every class before deciding where it is documented:

| The class is… | How to recognise it | Document it in |
|---|---|---|
| a **BAdI implementation** | implements `IF_EX_*` or a BAdI interface; bound by an `*.sxci.xml` or a `BADI_IMPL` in an `*.enho.xml` (content-search the class name) | the **enhancement's** document (or the BAdI host's) — declare both the class and the enhancement on its `**Covers:**` line. Two active implementations of one BAdI belong in one document |
| an **OData provider** | `*_DPC_EXT`, `*_MPC_EXT` (and generated `*_DPC` / `*_MPC`) | the **OData service's** document |
| a **REST resource or ICF handler** | inherits `CL_REST_RESOURCE` / `CL_REST_HTTP_HANDLER`, or implements `IF_HTTP_EXTENSION`; attached by a router's `attach( iv_template = … iv_handler_class = … )` | the **handler's or SICF node's** document — take the route from the `attach( )` call, never from the class name |
| a **workflow / event handler** for one process | called from one task or one program | that process's document |
| a provider in a **family** with an anchor document (e.g. a vendor-integration family `ZCL_XX_*`) | same superclass, same two methods | a family document named after one real member, all members on `**Covers:**` |
| a genuine **standalone** class | called from several unrelated hosts, or is itself an API | its own `docs/classes/<CLASS>.md` |

Before writing, check whether the host document already **walks** the class (search it for the class name): often it
does, and the class needs only a `**Covers:**` declaration and the retirement of stale "doc pending" markers — not a
new section.

### The direction problem — the reason satellites get missed

**A satellite names its host. The host contains no reference back.** Reading a transaction's metadata will
never reveal that a launchpad tile launches it; reading a service's ABAP will never reveal its authorization
defaults. So satellites cannot be found by drilling the host — they are found only by **searching the satellite
family for the host's name, and building a reverse index**.

Do this once per pass, not once per object:

1. Index every satellite family (they must be in the inventory — see Phase 1).
2. Build `host -> [satellites]` by scanning each satellite for host names.
3. When writing a host's doc, look its name up in that index and fold in what you find.

A satellite family that is absent from the inventory is invisible to this step, which is why a missing family
is far more damaging than a missing object: it removes a *fact type* from every document in the pass.

### Object-type census — run this before trusting any inventory

Extractors index the families they were taught. A repository can contain object types the extractor has never
heard of, and those types are then absent from every count, every coverage figure and every document — with no
error anywhere. **Audit the extractor against the filesystem at the start of every pass:**

```bash
# abapGit writes <object-name>.<objtype>.<rest> -- the type is the SECOND dotted segment,
# NOT the second-to-last (x.fugr.screen_0001.abap is a FUGR, not a "screen_0001").
find <repo> -path '*/src/*' -type f | sed 's|.*/||' | awk -F. 'NF>=3 && $2 ~ /^[a-z0-9_]{3,5}$/ {print $2}' \
  | sort | uniq -c | sort -rn
```

Diff that list against the families your extractor globs for. Anything present on disk and absent from the
index is a blind spot — classify each one as **host**, **satellite** or **out of scope**, and say which. Watch
particularly for a **whole modern stack** hiding behind unindexed extensions: RAP (`bdef` / `srvb` / `srvd` /
`ddlx`) publishes OData endpoints that no SEGW artefact mentions, so a repo's true service surface is the union
of both families — counting only the classic one can understate it substantially, and the RAP half is the
transactional half.

---

## Composite object families — what "one object" actually contains

Document each of these as **one** `.md`. Enumerate members with rule 11 (content search), and list every member
in section 3 with its resolved path.

| Logical object | Typical members | Where the behaviour is | Where the *authorization* answer is |
|---|---|---|---|
| **SEGW OData service** | SICF node · `.iwsv` · `.iwsg` · `.iwmo` · `.iwom` · `.iwpr` · DPC + DPC_EXT + MPC + MPC_EXT classes · any CDS view read · **1 `.sush` per service and per service group** | `*_DPC_EXT` redefinitions only | the `.sush` objects — *not* the ABAP |
| **RFC-enabled FM** | the FM source in its FG · the FG · **a `.sush` (type `RF`) naming `S_RFC`** | the FM | the `.sush` |
| **Transaction** | `.tran.xml` · target program/screen · includes · **possibly a `.sush` naming `S_START`** | the program | `AUTHORITY-CHECK` in code **plus** the `.sush` |
| **CDS-published service** | `.ddls.asddls` carrying `@OData.publish: true` — generates a service with **no SEGW artefacts at all** | the CDS itself | `@AccessControl.authorizationCheck` |
| **RAP application** | `.srvb` (one or more — V2/V4, UI/API) · `.srvd` · projection CDS (`C_*`) · interface/root CDS (`I_*`/`R_*`) with composition children · projection **and** base `.bdef` · behaviour pool `ZBP_*` (local `lhc_*`/`lsc_*`) · `.ddlx` metadata extensions · `.dcls` access controls · abstract entities for action parameters · V4 service group `.g4ba` / V2 `.iwsg` · `.sush` | the local handler classes of the behaviour pool (unmanaged/actions), else the framework (managed) | `.dcls` roles on the views, `authorization master` in the BDEF, the `.sush` — see *RAP applications* below |
| **BSP / UI5 application** | `<app>.wapa.xml` · every `<app>.wapa.<page>` file (`manifest.json`, `Component.js`, views, i18n) · SICF node `/sap/bc/bsp/sap/<app>/` · MIME (`*.smim.xml`) · launchpad target mapping (`*.wdcc.xml`) | the OData service named in `manifest.json` `dataSources` (plus any controller logic in the page files) | the service's `.sush` / `@AccessControl`, and the launchpad catalog |
| **BOR object type** | `<type>.sobj.xml` · its program (`SUBC = S`, often `Z<type>` or `ZR<type>`) · workflow tasks (`*.pdts.xml`) bound to it | the BOR program's `BEGIN_METHOD` blocks — or, for a subtype, the supertype's SAP code | whatever each method calls (BAPIs, `CALL TRANSACTION`); the BOR program itself rarely checks |
| **SAP query** | `<group> <query>.aqqu.xml` · InfoSet `*.aqsg.xml` · user group `*.aqbg.xml` · launching transaction (`REPORTTYPE=AQ`) | the InfoSet's joins and any InfoSet coding | user-group membership and the InfoSet authorization group — never an `AUTHORITY-CHECK` |

**Consequence for section 7.** "No `AUTHORITY-CHECK` in the code" is *not* the same as "no authorization". A
framework-level check declared in a `.sush` object, or a CDS `@AccessControl` annotation, is a real gate that the
ABAP never mentions. Check all three before writing section 7, and say which of the three you found. Conversely, a
`.sush` that declares a check with **no proposal** (`<PR_TEXT>No</PR_TEXT>`) is worth flagging: the check exists,
but role maintenance is given nothing, which is how blanket authorizations arise.

### RAP applications — one document per application

SAP layers a RAP application as follows (SAP Learning, *Building Transactional Apps with RAP — Concept and
Architecture*; SAP Help, *ABAP RESTful Application Programming Model*):

| Layer | Objects | What to read for |
|---|---|---|
| 1. Database | tables (incl. draft tables named in the BDEF) | §5 |
| 2. Data model | CDS **root view entity** + **composition children** (`composition of` / `association to parent`); plain interface views | §3.1, §4 |
| 3. Behaviour definition | base `.bdef`: `managed` / `unmanaged` / `with draft`, `authorization master`, CRUD, actions, determinations, validations, `implementation in class …` | §4 — the write surface |
| 4. Behaviour implementation | behaviour pool `ZBP_*`; **logic in the local `lhc_*` / `lsc_*` classes** of its local-types include | §4, §9 |
| 5. Projection | projection views (`as projection on`), **projection `.bdef`** (`use create`, `use action` — what the service may actually call), `.ddlx` metadata extensions (UI annotations) | §2 — what the user sees |
| 6. Service | `.srvd` (`expose X as Alias`), one or more `.srvb` (OData V2/V4 × UI/Web API), service group `.g4ba` (V4) / `.iwsg` (V2), `.sush` | §1, §3, §7 |

**The unit of one document is one service definition together with all its bindings** — a V2 and a V4 binding of
the same `.srvd` are one application; two `.srvd` are two applications, even when they sit on the same business
object. Rules, each learned from a real estate:

1. **One application, one document — never several applications merged into one.** Name the file after a real
   object (the binding, or the root view), and put every member on `**Covers:**`: binding(s), service definition,
   every exposed projection and the interface view under it, both `.bdef`s, the behaviour pool, the `.ddlx`s.
2. **Enumerate from the service definition downwards, by content search**: its `expose` list → each projection's
   `as projection on` base → `composition of` / `association to parent` / `redirected to composition child` →
   the `.bdef` named after any of those entities → the class after `implementation in class` → the `.ddlx`
   files that `annotate` any of them → the `.srvb` files naming the `.srvd`. Do not stop at filename prefixes.
3. **A business object shared by several services** (one root with children, exposed by three `.srvd`) is
   *described* in the document of the service that exposes the most of it, and *named* (not re-described) in the
   others. Value-help and text views shared across apps: same rule.
4. **A `.bdef` reached by no `.srvd`** is a business object without a service — document it as such (it may be
   consumed by EML from ABAP; search for `MODIFY ENTITIES` / `READ ENTITIES` on its name).
5. **A table row is not coverage.** An application document that lists its entities only in a table leaves them
   uncredited by a mention-count coverage rule; declare them on `**Covers:**` — after verifying each row's
   projection→base pairing and its source tables against the `.ddls` files.
6. **Read the projection `.bdef`, not only the base one**: the base may define `create`/`update`/`delete` while
   the projection exposes only `use action …` — the service's real write surface is the projection's.
7. **`unmanaged` means custom ABAP writes the data** (in `lsc_*` `save`); `managed` means the framework writes the
   tables named by `persistent table` — defects then live in determinations/validations, not in a save routine.

**Beware the second door.** The same table may be exposed twice — once by a SEGW service and once by a CDS view
with `@OData.publish: true`, often in a different package, often with different columns, different filters and a
different authorization posture. Finding one does not mean you have found the exposure. Grep the underlying table
name across `*.ddls.asddls` before concluding.

---

## Classifying a SICF node from its handler — do this before deciding scope

Rule 6 says a SICF node gets its own doc "when bespoke OR when it fronts an OData service". The handler class is
what tells you which, deterministically. Read the **handler table** (note the repeated-tag trap above — a node can
chain several handlers, in `ICFORDER` sequence):

| Handler class pattern | What the node is | Doc treatment |
|---|---|---|
| `/IWFND/CL_SODATA_HTTP_*` | An SAP Gateway OData endpoint | **Stub** (rule 10) pointing at the OData service doc. Pair node → service via `ICFALTNME` / `ICF_NAME` / the last URL segment, matched against `.iwsv` object names. All the analysis belongs in the service doc |
| Customer-namespace class | A **bespoke HTTP endpoint** | Full v1 doc. This is custom inbound attack surface — drill the handler class |
| Partner-namespace class | Add-on endpoint | Stub. Note that the source is usually not in the repo, so behaviour is undeterminable — say so rather than guessing |
| SAP-standard non-Gateway (e.g. generic form/RFC bridges, XI/PI handlers) | A standard service | Stub, but **flag it**: generic bridges that let a request name the object to execute are a materially different exposure from a purpose-built handler. State what you could not determine |
| *(none — empty handler table)* | A path node only | index-only |

In a typical repo the large majority of SICF nodes are Gateway OData endpoints. Classifying them first collapses
the apparent SICF backlog to the handful of genuinely bespoke nodes, and — more importantly — **converts every
one of the rest into a link between two families that would otherwise be documented as if unrelated**.

---

## Classifying a parameter transaction — a T-Code with no program is not a dead end

A transaction whose `<PGMNA>` is empty still does something. The target is in `TSTCP-PARAM`, serialized as
`<PARAM>` inside `*.tran.xml`. Parse it before concluding anything; the forms below mean different object
types, and only one of them is genuinely thin.

| `<PARAM>` form | What the transaction really is | Where the content is |
|---|---|---|
| `/*SM30 VIEWNAME=<v>;UPDATE=X;` or `;SHOW=X;` | **Table/view maintenance.** The host is the T-Code; the substance is the view, its table, the **maintenance object**, and any TMG event code | the `*.tabl.xml` / `*.view.xml`, the `*.tobj.xml`, and the generated maintenance function group |
| `/*SM34 VIEWCLUSTER=<vc>;` | View-cluster maintenance — several views edited together | the cluster definition plus every member view |
| `/*START_REPORT D_SREPOVARI-REPORTTYPE=AQ;...` | **An SAP Query (InfoSet query) launcher**, not a program at all | `EXTDREPORT` = query name, `REPORT` = user group. **abapGit does serialize queries** when they are transported in a package: look for `<group> <query>.aqqu.xml` (query), `*.aqsg.xml` (InfoSet) and `*.aqbg.xml` (user group) and document the query (see "Host families without ABAP files"). Only when no `*.aqqu.xml` exists is the query outside the repository — then record its name and say so rather than inventing behaviour |
| `/*<TCODE> <dynprofield>=<value>;` | A parameter/variant transaction onto another transaction | the target T-Code's doc; this one is **thin** and points at it |

Two traps worth stating:

- **`SHOW=X` is not an access control.** It only sets the *default* mode of that one transaction. A user holding
  the underlying table-maintenance authorization reaches the same table in change mode through the generic
  maintenance transaction. Never write "display only" in §7 on the strength of `SHOW=X` — write what the
  authorization objects actually permit.
- **The view name in `<PARAM>` is frequently not the transaction's name**, and is occasionally in lower case.
  Resolve it from the parameter string, never from the T-Code.

---

## Maintenance objects (`*.tobj.xml`) — liveness and authorization evidence for maintained tables

For any table reached through generated maintenance, the maintenance object is the **authoritative** record of
two facts that cannot be read off the code:

| Field | What it tells you | Section |
|---|---|---|
| `TDDAT-CCLASS` | The **table authorization class**. `&NC&` means *non-classified*: the table is not protected by a named authorization group, so generic table-maintenance authorization for the catch-all group reaches it | **§7** |
| `TVIMF` (`EVENT` + `FORMNAME`) | Exactly which form routines the maintenance dialog calls, and at which event (`01` before save, `05` new entry, `21` per-record before save, and so on) | **§4** |

**The liveness rule — check both directions before you call a form routine live or dead:**

1. A form routine in a maintenance function group is **not live** merely because it exists. If no `TVIMF` entry
   names it, the maintenance dialog never calls it.
2. A form routine is **not dead** merely because `TVIMF` does not name it. Grep for `PERFORM <form>` across the
   whole function group first — see the next point.

Getting this wrong in either direction produces a confidently-stated wrong answer: an unwired routine reported as
a live defect, or live code dismissed as generated scaffolding. Both are single-grep mistakes.

**Generated maintenance function groups are frequently reused as a home for hand-written function modules.**
Rule 9 lets you skip auto-generated DPC/MPC classes; it does **not** extend to maintenance function groups.
Enumerate the members of one before skipping it — the generated members follow a fixed naming shape
(`L<name>T00/F00/I00`, `SAPL<name>`, `TABLEPROC_*`, `TABLEFRAME_*`), and **anything else in the group is
hand-written business logic that no index will point you to.** That is a standing hiding place for substantive
code: it is reached by RFC or by a BAdI, never by the maintenance dialog, and it inherits none of the
maintenance transaction's apparent triviality.

---

## Embedded 11-section template

Use this skeleton for every per-object drill-down. A fully worked example of a compliant Full v1 doc ships as `example_doc.md` alongside this SKILL.md — consult it once per pass to calibrate depth and tone, especially for §4, §9, and §11. Fill every section; if a section truly does not apply (e.g. a CDS view has no "Authorization" entry), explicitly write "Not applicable — <reason>" so readers know the section was considered.

```markdown
# <Object type> `<NAME>` — <One-line purpose>

> **Quick facts** · Module: <SD/MM/FI/PM/PS/...> · Type: <T-Code / SICF / OData / BAdI / etc.> · Package: <Z...> · <Key URL or T-Code path> · Handler/Class/CDS: <ZCL_... / standard / etc.> · Source: `<package>/src/<file>`

---

## 1. End-User Story

<**State the business value first, and the interaction second.** Open with the business problem this object exists to solve: which process step it carries, which decision it feeds, who downstream depends on its output, and what it costs the business when it is wrong, late or skipped. Quantify wherever the source allows (volumes, amounts, how many people are blocked). Only then, and only as much as a business reader needs, say who touches it and what they get back.

**Both halves are required: the business benefit AND the human with their action.** Name the actual person — the parts adviser, the AP clerk, the branch stock controller, the buyer — and say concretely what they do and what they get back. Where no human is present (RFC, webhook, scheduled job), name the human who **triggers** it upstream: the service advisor booking in the other system, the cashier taking the deposit. "No SAP user" is a fact about the interface, never the whole answer. A section that gives the value but not the person is as incomplete as one that gives the person but not the value.

What is **not** an End-User Story is a walkthrough of the selection screen, the buttons and the output columns — that is §2 and §4 material and belongs there. If a reader finishes §1 knowing how to operate the object but not why the business runs it, the section has failed. If end users never see it (back-end callback / RFC / job), the value statement still applies: name the business process the integration serves and what breaks when it stops.

Where a defect changes the business outcome, close §1 with that consequence in business terms — what the wrong number causes, not which line produces it.>

---

## 2. Functional View *(for <SD/MM/FI/PM/...> consultants)*

> *Use the per-module cheat sheet in `module-vocab.md` (sibling file) to pick the right tables, BAPIs, and customising hooks for the module the object belongs to.*

### 2.1 Module placement
- **Primary:** <module + sub-module>
- **Cross-functional:** <other modules touched>
- **Equivalent standard:** <SAP standard FM / BAPI / Fiori app this replaces or wraps, if any>

### 2.2 Inputs
<entity keys, screen fields, URL params, file uploads>

### 2.3 Outputs
<documents posted, fields updated, files generated, JSON returned>

### 2.4 Customising
<config tables, transaction codes for setup, BC sets — high-level only; details in §8>

---

## 3. Technical Overview

| Field | Value |
|---|---|
| Object type | <T-Code / Program / Class / SICF / OData / BAdI / FUGR / CDS> |
| Object name | `<NAME>` |
| Package | `<Z...>` |
| Source path | `<package>/src/<file>` |
| Entry-point (if applicable) | <T-Code / URL / RFC FM name> |
| Handler / driver | <ZCL_... / program name / standard handler> |

### 3.1 Source-object table
<every Z-source file touched — programs, includes, classes, FMs, CDS views, tables. Skip minor DDIC.>

### 3.2 External dependencies
<DBE / DBME partner code / SAP standard FMs / RFC destinations / OS-level files / external HTTP endpoints>

---

## 4. Detailed Technical Spec

<Line-by-line or block-by-block walkthrough of the implementation. Don't paraphrase comments — describe what the code does. For long code, group by routine and include line numbers. Capture every branch.>

---

## 5. Database operations

| Table | Operation | When | Notes |
|---|---|---|---|
| <TABLE> | SELECT / INSERT / UPDATE / DELETE / MODIFY | <trigger condition> | <indexes hit, locks taken, batch size> |

---

## 6. External calls

<RFC / HTTP / function modules called outside this object. For each: target, parameters, error handling.>

---

## 7. Authorization

<Auth objects checked, S_TCODE / Z_AUTH_xxx, what happens on failure. If none, write "No explicit auth check — relies on T-Code/SICF gating".>

---

## 8. Customising / Configuration dependencies

<config tables read at runtime, IMG paths, BC sets, view clusters, parameter IDs (SPA/GPA). Each entry: what the config controls and what breaks if missing.>

---

## 9. Quirks / observations *(developer punch-list)*

<Honest list: hard-coded values (GL accounts, plant codes, dates), dead code, commented-out blocks, debug remnants (e.g. `BREAK-POINT IF sy-uname = 'DEVELOPER'`), German comments in an English-only system, naming inconsistencies, security gaps, broken date arithmetic, race conditions, places where new requirements would break the design. One bullet per quirk.>

---

## 10. Cross-references

- **Upstream callers:** <docs that reference this object>
- **Downstream callees:** <docs for objects this calls into>
- **Sister objects:** <related per-object docs in the same area>
- **Related enhancements:** <BAdI / Hook impls that touch this>
- **Related CDS:** <views consumed or exposed>

---

## 11. Inferences & assumptions

| Inference | Basis |
|---|---|
| <claim that cannot be verified from code alone but is best-guess> | <observed code pattern + naming + cross-reference that supports it> |
```

---

## Coverage matrix — paste-in template

Use this in `docs/_methodology.md` after Phase 2:

```markdown
| Area | Source objects | Per-object .md exists | Gap (substantive) | Action this pass |
|---|---:|---:|---:|---|
| T-Codes | <n> | <n> | <n> | <maintain / fill gaps / new> |
| Orphan programs | <n> | <n> | <n> | <…> |
| OData services | <n> | <n> | <n> | <…> |
| SICF nodes | <n> | <n> | <n> | <…> |
| Enhancements | <n> | <n> | <n> | <…> |
| Classes | <n> | <n> | <n> | <…> |
| Function groups | <n> | <n> | <n> | <…> |
| CDS views | <n> | <n> | <n> | <…> |
| Includes | <n> | n/a — folded into parent | n/a | n/a |
| DDIC (minor) | <n> | n/a — folded into parent | n/a | n/a |
```

---

## Recurring defect patterns worth grepping for

Patterns that recur across estates, are invisible to a casual read, and each need their own search because no
single grep finds them all.

### Session termination and foreign-lock breaking

Grep every estate for `TH_DELETE_USER`, `TH_DELETE_MODES`, and `ENQUEUE_DELETE` / `DEQUEUE_ALL` applied to locks
the current process did not set. Code that resolves a lock conflict by removing the *other* user is rare, severe,
and never documented by its author. Read the selection condition especially carefully: a filter such as
`WHERE tcode = 'X' OR tcode = 'Y' OR tcode IS INITIAL` looks narrow, but the `IS INITIAL` arm matches every
session whose current-transaction field is blank, which is far broader than the two named transactions. Note also
that the session-id parameter of the termination call defaults to *all sessions of that user*, not the one
holding the lock.

### Foreign-key domain mismatch in a lookup

`SELECT ... FROM <text-table> WHERE <key> = <field>` where `<field>` belongs to a *different* semantic domain
than `<key>`. The syntax is valid, the types are compatible, and the statement silently returns nothing — the
symptom is a permanently blank description rather than an error. Check that the field being compared is really
the key of the table being read, and that no intermediate mapping table was skipped. Pair it with the
missing-`sy-subrc` pattern: with no check, the target field is then overwritten with the initial value.

### Empty exception handling / template residue

`IF sy-subrc <> 0.` followed only by a comment, and in particular the generated comment that the SE37 pattern
insert leaves behind, is a reliable grep for "the author knew a failure was possible and shipped nothing". It is
worth a §9 entry whenever the swallowed exception is an authorization or communication failure.

### Duplicate near-identical routine pairs

Two form routines or methods whose bodies are identical apart from the name. Establish which is wired; the
unwired twin is dead code, and any defect in the live one is usually present in both, so a fix applied to one
silently leaves the other wrong. The same shape at file scale — a forked program with its own copy of every
include — is the higher-value version of this hunt: diff the forks routine by routine and look for a fix present
on one side only.

### Hard-coded waits in background or update processing

`WAIT UP TO n SECONDS` inside a function module called `IN BACKGROUND TASK`, an update module, or a BAdI
implementation. It is almost always a timing workaround for a race the author could not otherwise resolve, it
occupies a work process for the duration, and it makes the surrounding logic order-dependent in a way no caller
can see.

### Wrong-alias join condition (multi-alias self-joins)

When one table is joined several times under different aliases, the `ON` clause of a later join sometimes
constrains an **earlier** alias instead of the one being introduced:

```abap
LEFT OUTER JOIN <tab>          ON <tab>~key = <parent>~key AND <tab>~f = 'A'
LEFT OUTER JOIN <tab> AS alias ON <tab>~key = <other>~key  AND alias~f = 'B'   " <-- alias~key never constrained
```

The new alias is then restricted only by its non-key filter — or by nothing at all — so it matches **every**
row of the table rather than one. With an outer join that multiplies result rows; the caller sees duplicated
lines, or a single arbitrary value where one specific row was intended.

**Why it survives review:** the `ON` clause looks perfectly normal. Both operands are real, different columns,
so the self-comparing-`WHERE` check does not fire, and every alias *is* mentioned somewhere on the line.

**How to find it:** for each `JOIN <tab> AS <alias>`, check that `<alias>~` appears on the **key side** of its
own `ON` clause — not merely somewhere in it. Anything else is suspect.

**Read the neighbours before judging severity.** These cluster: one `SELECT` may carry several address or text
self-joins where some are right and some are wrong. A correct sibling a few lines away is strong evidence of a
slip rather than intent, and it tells you what the author meant — which is exactly what a remediation note
needs. Aliases resolving to contact data (telephone, e-mail) on a document handed to a customer are the
highest-consequence instances.

### Related predicate-level patterns

- **Self-comparing `WHERE`.** In classic un-escaped Open SQL, when a host variable shares a name with a column
  of the table being read, **the column wins** and the predicate is always true. Escaped/strict syntax (`@`
  prefixes) makes this impossible, so it is a legacy-code pattern.
- **Always-true `OR`.** `IF x <> 'A' OR x <> 'B'` — a variable cannot equal both literals, so at least one
  operand is always true. Almost always a mis-typed `AND`.
- **Empty range tables.** `WHERE f IN <range>` with an empty range matches every row. This is how an unfiltered
  API call or a blank selection screen turns into a full-table read — check for an upper bound, not just for a
  filter.
- **Sign tests standing in for indicator fields.** Deriving a classification from the sign of an amount rather
  than from the field that carries it: the two agree until a zero, a reversal or a sign convention differs.

---

## Anti-patterns — common failure modes

- **Giving a satellite its own document.** An authorization-default object or a launchpad config documented
  standalone says nothing; the same content inside its host's §7 or §1 answers a real question. One file per
  *host*, satellites folded in.
- **Describing the same shape three times instead of counting it.** When a pattern turns up in three
  unrelated drills — a hard-coded user check, a leading-wildcard `LIKE`, a pre-exit that exits, a posting date
  taken from the wrong document — stop writing it up locally and measure it across the repository. Three local
  observations are three anecdotes; one census is a finding with a denominator, and it usually takes a single
  script over a few hundred files. The census also reveals the *shape* of the habit: which packages, which
  vendor objects, whether it concentrates on one function group.

- **Reporting a count without stating what it was measured over.** Any repository-wide number — occurrences,
  "none found", objects in a family — is only meaningful with its file set named. Three traps recur:
  *(a)* a `*.abap` glob misses ABAP embedded in form/Smart Form XML; *(b)* a display limit is not a result —
  printing the first N of M matches and reasoning from them will invent conclusions the data contradicts, so
  count first and print second; *(c)* a raw diff line count is not a divergence measurement unless it is
  case-normalised — a file that was pretty-printed with a different case setting can report hundreds of
  "changed" lines that carry no semantic difference at all.

- **Asserting SAP standard behaviour from memory** (hard rule 2 — look it up, cite it, fold it into the caller). A claim about what an SAP statement, exit or BAPI
  does is as much a finding as a claim about the custom code, and carries the same obligation to verify. These
  claims are especially dangerous because they propagate: an unverified sentence about a language construct gets
  copied into every document that meets the construct again, and into the findings register, before anyone
  checks it. Look it up, cite the source in the doc, and when a later drill contradicts an earlier claim,
  correct every place it was written - not just the newest one. Distinctions that sound like detail and are not:
  `BREAK-POINT` versus `BREAK-POINT ID` (the second is inert in background/update sessions and switchable at
  runtime; the first is neither), `SELECT SINGLE` with and without `ORDER BY`, aggregate `SELECT`s returning
  `sy-subrc = 0` on an empty table, and unescaped operands in classic Open SQL resolving to columns.
- **Writing a second document for an object that is already documented under another area.** An object
  belonging to two families — a RAP service and its root CDS view, a T-Code and its target program, a form
  and its print program — is filed under whichever family the first author treated as primary. Arriving from
  the other direction and searching only the area you intend to write into finds nothing, and you produce a
  duplicate. Search **every** `docs/<area>/` folder for the name first, and if a doc exists, extend it. The
  give-away that this has already happened: two documents whose §4 sections describe the same code from
  different angles, neither linking to the other.
- **A `SE:BEGIN` enhancement that ends in `EXIT.` — the silent replacement.** A source-code plug-in at
  position `SE:BEGIN` runs *before* the enhanced method, routine or function module. Ending it with `EXIT.`
  leaves that object immediately, so **the body being enhanced never executes**. The enhancement is not an
  extension; it is a replacement wearing an extension's name, and nothing announces it: no activation error,
  nothing in the short text, and the enhanced object still reads as working code. The practical cost is on
  upgrade — a vendor correction to that method is transported in, activates cleanly, and is skipped at
  runtime. The give-aways are (a) the plug-in opens with a re-implementation of the vendor's own logic, often
  with locals suffixed `2`/`3` to dodge name clashes with the enclosing scope, and (b) the last live statement
  is a bare `EXIT.`. Grep for it directly — the header line of each implementation carries its position:

  ```bash
  # every SE:BEGIN plug-in whose body ends in EXIT
  for f in $(grep -rl 'SE:BEGIN' --include='*.enho.*.abap' .); do
    grep -qE '^\s*exit\s*\.' "$f" && echo "$f"
  done
  ```

  Report it as a count, not an anecdote: *N of M `SE:BEGIN` implementations replace the body they enhance.*
  And note in §11 that the replaced bodies are vendor code **not serialized in the repository**, so the copies
  cannot be diffed against their originals — how far each has drifted is not answerable from source, which is
  itself part of the finding.
- **Attributing a customer-exit include from its name.** SAP derives the customer include name
  (`ZX<fg><type><nn>`) from the **function group** that hosts the exit function module, *not* from the
  enhancement. Two unrelated SMOD enhancements whose exits live in the same function group therefore share an
  include prefix, and nothing in the filename says which enhancement owns which include. Attribute each include
  from evidence inside it - the pasted interface comment naming its `IMPORTING`/`CHANGING` parameters is
  decisive, because each exit has a distinct signature - or from a checkpoint group / naming convention it
  shares with its siblings. This is the same trap as "the include number is not the exit number", one level up:
  **a shared prefix is not evidence of shared ownership.**
- **Treating a generated function group as skippable without listing its members.** Generated maintenance
  function groups routinely host hand-written function modules that have nothing to do with maintenance. The
  generated members have predictable names; everything else is business logic, and it is exactly the code an
  index will never surface.
- **Calling a routine live or dead from one piece of evidence.** For maintenance function groups, the event
  wiring and a `PERFORM` grep answer different halves of the question. Check both before writing either verdict.
- **Iterating over abapGit filenames with shell word-splitting.** `for f in $(find ...)` silently drops every
  path containing whitespace, and abapGit pads some serialized filenames with spaces. The loop reports a clean
  result over a subset, so the count is wrong and nothing warns you. Use `find -print0` with `while read -d ''`,
  or do the walk in a language with real path handling. Any count produced by such a loop must be re-derived.
- **Writing §7 from the ABAP alone.** "No `AUTHORITY-CHECK`" is a statement about the code, not about the
  system. Check three sources — the ABAP, framework-level authorization defaults, and any CDS `@AccessControl`
  annotation — and say which you found. A finding that rests on only the first will overstate severity.
- **Trusting the inventory's family list.** Run the object-type census (above). A family the extractor never
  learned is invisible, and so is every fact it carries.
- **Trusting a count you have not re-derived.** Any claim of the form *"there are N of X"* should be measured
  from source and then re-measured a second, structurally different way before being written down. When a fresh
  check disagrees with a long-standing figure, suspect the fresh check first — a shallow directory walk or a
  regex that matches a wrapper tag instead of a leaf will both produce confident wrong answers.


Watch for these. Each has bitten real passes.

1. **Trusting filenames over XML content.** AbapGit serializes some objects under SAP-generated names. Always extract logical names from XML.
2. **"Add stub later" deferral.** Becomes a permanent gap. If methodology says a stub is warranted, produce it in the same pass.
3. **Aggregate-doc-instead-of-per-object.** Saves typing but loses navigability. One `.md` per substantive object — non-negotiable.
4. **Assuming colocation by package.** SICF in one package, OData impl in another, helper FUGR in a third. Follow references across boundaries.
5. **Documenting metadata, not behaviour.** Reading the `.iwsv.xml` and calling it done. The behaviour is in the `.clas.abap`. Read the source.
6. **Hiding defects.** Hard-coded GL accounts, dead DPC classes, debug `BREAK-POINT`s, German comments — these all go in Quirks. Sanitised docs help no one.
7. **One-way cross-references.** Linking the class doc to its OData service but not updating the OData service doc to link back. Always update both ends.
8. **Forgetting to refresh inventory.** Running a pass against stale `docs/_index/raw/*.tsv` misses objects added since the last pass.
9. **Skipping the End-User Story for back-end callbacks.** Even a webhook has a user — the human triggering the upstream system. Write the story.
9b. **Writing the End-User Story as a click-path.** *“The user opens the transaction, fills the selection screen, presses execute and sees an ALV”* is a dummy story: it describes operation, not value. It reads as complete, passes every structural check, and tells a business reader nothing about why the object exists or what it costs when it is wrong. §1 must answer **what the business gains**; the screen, the buttons and the columns belong in §2 and §4. Reviewers reject otherwise-compliant documents for exactly this — structure is not the problem.
10. **Treating "Inferences" as filler.** That section is where you mark which conclusions are read-from-code vs read-from-naming. Auditors rely on it to spot weak claims.
11. **Merged numbered sections.** `## 4-8. Details / DB / External / Auth / Customising` is a compliance failure. Each of the 11 required sections must be its own numbered header, even when the content is a single line saying `_Not applicable — <reason>_`. The compliance script rejects merges.
12. **Compact-generator output treated as a compliant doc.** A doc emitted by `generate_*_docs.py` in its short-form (< 11 sections) is a structural gap, not a completed doc. Never mark a tree "closed", a batch "CLOSED", or coverage "complete" while compact-tier docs still exist in the output. Regenerate them through the 11-section skeleton path first.
13. **Trusting sub-agent completion claims without sample-check.** When a sub-agent reports `N docs written · Full v1 tier · CLOSED`, that claim is unverified until the parent opens 3 random docs from the output and confirms all 11 section headers are present. Enforce this via Phase 3.5.
14. **Header-shell drift.** Mid-run (especially in long parallel batches) an agent emits all 11 headers but with empty bodies, skeleton residue, generic off-topic filler, or the same §4 pasted into many docs. This passes a header-only check while containing zero documentation value. The compliance script's hollow detection (H1–H6) exists precisely for this; dispatch rules 7–10 prevent it at the source (small batches, per-object source paths, mid-batch self-gates).
15. **Wrong-grammar reads.** Starting in the wrong file per object flavor: documenting a parameter transaction by hunting for a program that doesn't exist; reading a generated DPC base class instead of the _EXT redefinitions; opening a RAP behavior-implementation global class, finding it empty, and concluding "no logic" (it's in the local lhc_*/lsc_* classes); ignoring dynpro PBO/PAI flow logic on dialog transactions. Select the grammar from `reading-grammars.md` BEFORE reading.

---

## Sub-agent dispatch rules

When dispatching sub-agents that generate or upgrade docs:

1. **Every sub-agent prompt MUST require sample-header evidence.** Include this line in every dispatch prompt: *"In your final report, paste the exact `##` section headers of 3 random docs you wrote. This is required — reports without it will be treated as unverified."*
2. **The parent MUST verify the samples** contain all 11 required numbered section headers before accepting a "CLOSED" claim. If any sample is missing a section, treat the entire batch as unverified and re-run `check_template_compliance.py` on the sub-agent's output paths.
3. **The parent MUST run the compliance script** on the sub-agent's output paths as part of Phase 3.5, regardless of the sub-agent's own report. Two-stage gate: script always runs; reviewer agent dispatched only on script failure.
4. **Parallel sub-agents are allowed by object family** (Enhancements / OData / WEBI / CDS / SICF / etc.). Different families have no cross-references, so parallel dispatch is safe.
5. **Parallel sub-agents within a single tree walk are forbidden.** Reciprocal cross-references become race-prone. Tree walks are always inline.
6. **When a sub-agent hits an API error or timeout mid-batch**, do NOT accept its partial output as CLOSED. Re-dispatch or continue inline. Run the compliance script on whatever it managed to write before deciding.
7. **Batch-size cap: ≤ 8 docs (or ≤ 2 T-Code trees) per sub-agent dispatch.** Long batches are where drift happens — the agent stops re-reading source and starts emitting filler. Multiple small dispatches cost roughly the same tokens as one big one but each stays anchored, and a drifted batch loses at most 8 docs instead of 40.
8. **Every dispatch prompt MUST enumerate, per object: the object name, its exact source file path(s), AND the applicable reading grammar** (from `reading-grammars.md` — e.g. "classic 1b dialog txn", "SEGW grammar 2", "RAP grammar 3"). The agent must open the source file immediately before writing each doc — never write a doc from memory of an earlier read. An agent that cannot find a listed source path must report it (DOC-002 candidate), not improvise content.
9. **Every dispatch prompt MUST include a mid-batch self-gate:** after every 4 docs, the agent runs `check_template_compliance.py --strict --paths <the docs it just wrote>` and fixes any partial/hollow finding before continuing. This costs one cheap script run and stops drift from compounding across the rest of the batch.
10. **The parent gates each batch with `--paths` on arrival** (not just the end-of-session repo-wide run): `python "$SKILL_DIR"/scripts/check_template_compliance.py --repo-root . --strict --paths <batch docs>`. Hollow findings mean the batch drifted — re-dispatch ONLY the flagged docs with their source paths restated, not the whole batch.
11. **Every dispatch prompt MUST paste the "Drill-down hard rules" block verbatim.** A sub-agent does not inherit this skill; rules it never saw do not bind it.

---

## Memory and cross-session continuity

When working in a repo for the first time:
- Save a `feedback` memory if you discover any project-specific deviation from this methodology (e.g. "this client uses `Y*` namespace, not `Z*`").
- Save a `project` memory if you learn who owns what, deadlines, or compliance constraints.
- Save a `reference` memory if there are external systems the docs reference (Linear projects, Confluence pages, Grafana dashboards).

When resuming work in a repo on a later session:
- Check `docs/_methodology.md` coverage matrix first — that's the live worklist.
- Re-run Phase 1 inventory before assuming the matrix is current.
- Check the area's TSV vs the area's `.md` folder for newly-added objects.

---

## Companion skill — single-object drill-downs

For one-off "document this single object" requests, the companion skill `/abap-document-object` applies the same 11-section template without running the full inventory or coverage-audit dance. Use it for ad-hoc requests like "drill T-Code ZXX01" or "write the doc for `ZCL_FOO_BAR`". It still updates reciprocal cross-references on linked existing docs.

When to escalate from `/abap-document-object` to a full `/abap-documentation` pass:
- The repo's `docs/_index/raw/*.tsv` is stale or absent.
- The single-object drill exposes a hidden-alias pattern affecting many objects in the same family.
- Multiple linked objects also lack docs (more than 2–3 dangling pointers).

---

## Sibling reference files

This skill ships with these sibling files alongside `SKILL.md`:

- **`scripts/extract.py`** — Phase-1 inventory harness. Walks any abapGit repo, emits one TSV per object family into `docs/_index/raw/`, prints a hidden-alias report.
- **`scripts/render_indices.py`** — Renders the TSVs into navigable `docs/_index/<family>.md` markdown tables (both on-disk name and friendly name visible).
- **`scripts/validate.py`** — Phase-4 coverage + link validator. Reports gaps, orphan docs, broken markdown links. Supports `--strict` for CI.
- **`scripts/check_template_compliance.py`** — Phase-3.5 gate. Classifies every per-object doc as compliant / partial / hollow against the 11-section template; `--strict` for a hard gate.
- **`scripts/render_docx.py`** — Phase-5 (optional) DOCX renderer. Mirrors `docs/**/*.md` to `docs_docx/**/*.docx` via pandoc, incremental by mtime.
- **`reviewer_agent_prompt.md`** — Prompt for the compliance-reviewer sub-agent dispatched when Phase 3.5 fails.
- **`reading-grammars.md`** — Deterministic per-flavor reading orders (classic T-Code flavors incl. dynpro flow logic, SEGW OData backwards-from-_EXT, RAP local handler classes, CDS stacks, enhancements, OO classes) plus the classic side-door checklist. Consult at the start of every drill.
- **`example_doc.md`** — Worked example of a compliant Full v1 doc (fictional object). Calibration reference; never copy into a repo.
- **`module-vocab.md`** — Per-module cheat sheets (SD / MM / FI / CO / PM / PS / PP / HR / VSS / cross-cutting). Reference when filling §2 "Functional View".

All Python scripts are stdlib-only (`render_docx.py` shells out to `pandoc`). Run from the repo root:

```bash
# Full Phase-1 → Phase-4 cycle
python "$SKILL_DIR"/scripts/extract.py
python "$SKILL_DIR"/scripts/render_indices.py
python "$SKILL_DIR"/scripts/validate.py

# Phase-5 (optional, requires pandoc on PATH)
python "$SKILL_DIR"/scripts/render_docx.py
```

---

## Quick-start checklist

When asked to document a new ABAP repo or extend an existing one:

- [ ] Re-read the **Drill-down hard rules** at the top of this skill — they bind every step below.
- [ ] Read `docs/_methodology.md` if it exists — apply repo-specific deviations. Confirm its **"Namespaces in scope"** list (Z, Y, plus any partner namespace); if the repo holds an unrecorded `/XXX/` namespace, ask the user and record the answer.
- [ ] Check `docs/_index/sap_standard.md` (create it if absent) — the shared SAP-standard lookup table (hard rule 2).
- [ ] Phase 1: `python "$SKILL_DIR"/scripts/extract.py` — regenerate TSVs, review hidden-alias report.
- [ ] Phase 1: `python "$SKILL_DIR"/scripts/render_indices.py` — render navigable indexes.
- [ ] Phase 2: build/refresh coverage matrix. Classify every TSV row as substantive / stub / index-only.
- [ ] Phase 3: drill substantive objects in priority order, 11-section template each.
- [ ] Phase 3: produce same-pass stubs for routing-only Z objects (no deferrals).
- [ ] **Phase 3.5 (mandatory): `python "$SKILL_DIR"/scripts/check_template_compliance.py --repo-root . --strict` — verify 11-section compliance on session outputs. On failure, dispatch reviewer agent per `$SKILL_DIR/reviewer_agent_prompt.md`. Do NOT proceed until this passes.**
- [ ] Phase 4: update reciprocal cross-references on every linked doc.
- [ ] Phase 4: update area READMEs and `docs/MASTER_INDEX.md`.
- [ ] Phase 4: `python "$SKILL_DIR"/scripts/validate.py --strict` — verify coverage, orphans, links, AND 11-section compliance (strict mode now includes compliance check). Investigate any issues before commit.
- [ ] Phase 5 (optional, before stakeholder handoff): `python "$SKILL_DIR"/scripts/render_docx.py` — render `docs_docx/` parallel tree via pandoc.
- [ ] Propose a commit per family or per phase (never one giant commit). Commit and push **only after the user's explicit OK** (hard rule 9).
