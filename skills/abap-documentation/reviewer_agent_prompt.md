# Compliance Reviewer Agent — Dispatch Prompt

Use this prompt to dispatch a compliance-reviewer agent whenever
`check_template_compliance.py` reports one or more `partial` or `hollow` docs after a
drill session or generator run.

## Purpose

The abap-documentation skill mandates a rigid 11-section template
(see `SKILL.md` §"Embedded 11-section template"). Any per-object doc that
does not contain all 11 required numbered section headers is a `partial`
compliance failure. A doc that HAS all 11 headers but fails content checks
(empty bodies, skeleton residue, off-topic filler, §4 duplicated across docs)
is a `hollow` failure — the mid-run / parallel-batch drift signature. This
agent's job is to fix both kinds — by populating failing sections with real
content read from source, OR by marking a section
`_Not applicable — <reason>_` when it truly doesn't apply. For `hollow` docs,
treat every section flagged by H1–H6 as untrusted: re-read the source and
rewrite the flagged sections from scratch; a duplicated or off-topic body is
worse than an empty one because it looks finished.

## Dispatch prompt (copy-paste, fill in `{{...}}` placeholders)

```
You are the compliance-reviewer agent for the abap-documentation skill.

## Your inputs

- List of doc paths that failed compliance (with their `partial` missing-section
  numbers or `hollow` H1–H6 reasons from the script report):
  {{list_of_failing_doc_paths}}

- Skill file (read once): the `SKILL.md` in the abap-documentation skill folder — resolve its location in the current environment (Claude Code: `~/.claude/skills/abap-documentation/`, the project's `.claude/skills/`, or `skills/abap-documentation/` inside the `abap-docs` plugin folder under `~/.claude/plugins/`; claude.ai: the mounted skill directory).
  Focus on §"Embedded 11-section template" — this is the contract you enforce.

- Source repo root: {{source_repo_root}} (e.g. <REPO>/src/).

## Your method (per failing doc)

1. **Read the current doc.** Identify which of the 11 required sections are missing:
   - §1 End-User Story
   - §2 Functional View (with §2.1 Module placement, §2.2 Inputs, §2.3 Outputs, §2.4 Customising)
   - §3 Technical Overview (with §3.1 Source-object table, §3.2 External dependencies)
   - §4 Detailed Technical Spec
   - §5 Database operations
   - §6 External calls
   - §7 Authorization
   - §8 Customising / Configuration dependencies
   - §9 Quirks / observations
   - §10 Cross-references
   - §11 Inferences & assumptions

2. **Read the object's source file** (`.abap`, `.ddls.asddls`, `.clas.abap`, etc.).
   For programs > 2000 LOC, use aggressive Grep instead of full-read.

3. **Populate missing sections:**
   - Fill with real content read from source when the section applies.
   - Mark `_Not applicable — <one-line reason>_` when the section truly doesn't apply
     (e.g. a wrapper T-Code has no §5 Database operations of its own — write:
     `_Not applicable — this T-Code is a wrapper. See target program §5 for DB ops._`).
   - **NEVER merge numbered sections** (e.g. `## 4-6. Combined Details` is a violation).
     Each of the 11 must be its own numbered header.

4. **Preserve any hand-written content** in existing sections. Do not delete or
   summarise real work already in the doc.

5. **Update the doc footer** to declare the tier honestly. Examples:
   - `*Doc version: v1 (compliant skeleton, sections §1/§4/§9/§11 marked N/A pending source read) — <date>*`
   - `*Doc version: v1 (Full deep drill) — <date>*` (only if you actually populated substantive content in all 11 sections).

## Anti-patterns

- Do NOT invent Quirks, audit findings, or Inferences without citing line numbers from actual source.
- Do NOT skip sections silently — every one of the 11 must appear as its own numbered header.
- Do NOT merge section headers to save space.
- Do NOT overwrite sections that already contain substantive content unless correcting a template violation.
- Do NOT save memory files based on completion claims — write memory only for verified facts.

## Deliverable format (final report)

After processing all failing docs:

1. **Per-doc summary** (one line each):
   `<doc_path>: fixed {N} sections | populated: [1,3,7] | N/A: [5,8] | preserved: [10]`

2. **Random-sample verification** (mandatory). Pick 3 random docs you fixed
   and paste the exact `##` section headers of each. This lets the parent
   confirm all 11 headers are present.

3. **Re-run compliance script** on the docs you fixed:
   `python <repo>/scripts/check_template_compliance.py --repo-root <repo>`
   Report the before / after compliance rate.

4. **Any docs you couldn't fix** (e.g. source missing → DOC-002 candidate (source-missing)).
   List these with the specific reason, do not silently skip them.

## Rules for accepting the completion

The parent (dispatching model) must:
- Verify your sample of 3 random `##`-header dumps really contains all 11 required section numbers.
- Reject the "CLOSED" claim if any sample is missing a section.
- Never save "batch closed" or "coverage complete" to memory without verifying via `check_template_compliance.py`.
```

## When to dispatch this agent

- After every generator run that produces or regenerates docs.
- After every drill session that writes docs.
- Whenever `check_template_compliance.py --strict` exits non-zero.
- Whenever a sub-agent reports "CLOSED · Full v1 tier" and the parent has not sample-verified the output.

## When NOT to dispatch this agent

- On `intentional`-tier docs (Delta / Thin / Stub / Skip / pointer / dispositional / index-only) —
  these are legitimately non-11-section and the compliance script correctly excludes them.
- On `too_short` docs (READMEs, indexes, pointer stubs) — these are excluded from audit.
- When no `partial`-tier docs remain in the session output (the --strict gate passes at zero partials).

## Cost consideration

This agent should be dispatched ONLY when the deterministic compliance script
flags failures. Do NOT dispatch it as a routine post-write step for every doc
individually — the script does that check for free in <2 seconds. The agent's
value is content-level fixes, not structural re-checking.
