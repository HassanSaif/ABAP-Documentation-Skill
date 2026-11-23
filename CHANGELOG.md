# Changelog

## 1.1.0 — 2026-11-23 — generic, publishable release

Plugin `abap-docs` 1.1.0: `abap-documentation` 2.3.1, `abap-document-object` 2.1.1, `abap-module-index` 1.8.1.

### Added
- MIT `LICENSE` (and `"license": "MIT"` in `plugin.json`) — required for the Claude plugin directory.
- Plugin icon `.claude-plugin/icon.png`.

### Changed
- All three skills are now fully generic. Removed from comments, docstrings and reference docs:
  - counts and measurements taken from the original client estates (object, unit and edge counts, and signal-accuracy percentages, which are now a ranking plus "measure with `measure_signals.py`")
  - internal fix history and dates
  - client-flavoured object names, entity codes, folders, and industry or country hints
  Every rule keeps its generic rationale.
- `render_indices.py`: the SXCI index note no longer prints one estate's counts; it states the general dedup formula.
- `validate.py`: a comment that contradicted the code on subroutine-pool scope now matches the code.
- No code behaviour changed. This was verified by an AST comparison and by identical output on a sample repo.

## 1.0.0 — 2026-11-22 — first shared release

Plugin `abap-docs` 1.0.0, containing `abap-documentation` 2.3.0, `abap-document-object` 2.1.0 and `abap-module-index` 1.8.0.

### Added
- **Drill-down hard rules** — a binding MUST / MUST NOT block at the top of `abap-documentation` and
  `abap-document-object`. It covers custom-namespace-only drilling with no depth limit, web lookup of SAP-standard
  objects folded into the calling doc, no claim without a `file:line` source, modules decided from evidence,
  read-only outside `docs/`, no overwriting docs, and no commit/push without approval.
- `docs/_index/sap_standard.md` — a shared, per-repo table of SAP-standard lookups.
- Sub-agent dispatch rule 11: every dispatch prompt carries the hard rules verbatim.
- `abap-module-index`: a non-negotiable that the module list is guidance, never a boundary.
- `module-vocab.md`: explicit "open list" note.
- `validate.py --sicf-handler-namespace NS` (repeatable) for partner-namespace SICF handlers.
- Plugin + marketplace manifests, copy installers (`tools/install.ps1`, `tools/install.sh`), and
  `tools/package_skills.py` (claude.ai upload validation + zips).

### Changed
- Partner namespaces `/DBE/` and `/DBME/` are no longer hard-wired into `validate.py`. Pass
  `--sicf-handler-namespace DBE --sicf-handler-namespace DBME` to get the previous behaviour.
- `render_indices.py`: the TOBJ index banner no longer prints one client repository's counts and file names.
- "Commit per family / push when complete" became "propose the commit, wait for approval".
- Tree walks follow every *custom* callee (Z / Y / in-scope partner namespace), not just `Z*`.
- Frontmatter: `version` moved under `metadata`, and angle brackets were removed from descriptions (claude.ai upload rules).
  The `abap-module-index` description was shortened to fit within 1024 characters.
- Client object names in code comments were replaced with neutral placeholders (`ZXX_…`).
- Script paths printed by `validate.py` resolve relative to the installed skill instead of `~/.claude/skills`.

### Removed
- `.bak` snapshots and `__pycache__` from the shipped skills.
