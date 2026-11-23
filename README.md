# ABAP Documentation Skills for Claude

[![GitHub stars](https://img.shields.io/github/stars/HassanSaif/ABAP-Documentation-Skill?style=social)](https://github.com/HassanSaif/ABAP-Documentation-Skill/stargazers)

> ⭐ **Using these skills? Please star this repository before you install them.** It is free, it is the only way
> I can see who uses the methodology, and it helps other SAP teams find it.

Three Claude skills for documenting SAP ABAP code exported with **abapGit**. They give every team member the same
methodology, the same 11-section template, and the same hard rules, whichever Claude account they use.

| Skill | Use it for | Example prompt |
|---|---|---|
| **`abap-documentation`** | Repo-wide passes: inventory → coverage audit → per-object drill-downs → cross-references → validation | *"Document this ABAP repo"*, *"Audit the docs for missing objects"* |
| **`abap-document-object`** | One named object (T-Code, class, OData service, BAdI impl, FUGR, CDS view, program) | *"Document T-Code ZSD_001"*, *"Drill ZCL_FOO_BAR"* |
| **`abap-module-index`** | Module ownership workbook: which SAP module (SD, MM, FI, …) has a stake in each custom entry point, with evidence | *"Which module owns this custom code?"*, *"Build the module index"* |

`abap-document-object` uses the template, `module-vocab.md` and `reading-grammars.md` from
`abap-documentation`, so **always install those two together**.

---

## Drill-down hard rules (summary)

Both documentation skills carry a binding **"Drill-down hard rules"** block at the top of their `SKILL.md`. In short:

| # | Rule |
|---|---|
| 1 | Drill **custom code only**: `Z*`, `Y*` and any partner namespace (e.g. `/DBE/`) listed in the repo's `docs/_methodology.md`. No depth limit for custom code. An unlisted namespace means Claude asks you first. |
| 2 | **Never drill SAP standard.** For a standard BAPI / FM / class / table, Claude runs a quick web search on what it does, writes a 1–2 line summary into the *calling* custom object's doc (§5 or §6) with the source URL, and records it in `docs/_index/sap_standard.md` for reuse. |
| 3 | A branch stops only at SAP standard, an unresolvable dynamic call, or an object missing from the export — each stated in §11. |
| 4 | **No claim without source**: behaviour must cite `file:line` from a file opened in that session. Anything else is an inference, in §11. |
| 5 | **Modules come from evidence, not from a list.** The module cheat sheets are guidance; the module is decided from the tables the code writes and reads, including modules not on any list. |
| 6 | All **11 sections**, each its own numbered header, passing the compliance script. |
| 7 | **Read-only outside `docs/`** — defects are documented in §9, never fixed. |
| 8 | **Never overwrite a doc** — an existing doc is read in full and extended. |
| 9 | **No commit or push** without your explicit OK. |

`abap-module-index` applies rule 5 too: its module list is open, and every module is checked against the tables the code actually writes.

---

## Requirements

- **Claude Code** (CLI, desktop or IDE extension) — recommended, because the skills run Python scripts on your local repo.
  Or **claude.ai** with Skills enabled (Settings → Capabilities).
- **Python 3.10+** on `PATH`. The documentation scripts use only the standard library.
- Optional: **pandoc**, for DOCX rendering (`render_docx.py`); **openpyxl** (`pip install openpyxl`), for the module-index workbook.
- Web search enabled in Claude, so rule 2 can look up SAP-standard objects. Without it, those summaries are marked `(unverified)`.

---

## Install

**Step 0 — ⭐ star the repo** at https://github.com/HassanSaif/ABAP-Documentation-Skill (top-right **Star** button).

### Option A — Claude Code plugin (recommended: one command to update)

Inside Claude Code:

```
/plugin marketplace add HassanSaif/ABAP-Documentation-Skill
/plugin install abap-docs@abap-docs-marketplace
```

Restart Claude Code. The skills appear as `abap-docs:abap-documentation`, `abap-docs:abap-document-object` and
`abap-docs:abap-module-index`. Claude also picks them up automatically from prompts like the examples above.

To update later: `/plugin marketplace update abap-docs-marketplace`.

### Option B — copy into your skills folder

```powershell
git clone https://github.com/HassanSaif/ABAP-Documentation-Skill.git
cd ABAP-Documentation-Skill
.\tools\install.ps1            # Windows → %USERPROFILE%\.claude\skills
.\tools\install.ps1 -Project   # or only for the current project → .\.claude\skills
```

```bash
./tools/install.sh             # macOS / Linux / Git Bash → ~/.claude/skills
./tools/install.sh --project   # or ./.claude/skills
```

An existing copy is moved to `~/.claude/skills-backup/` first, never deleted. To update, `git pull` and run the installer again.

> Use **either** A **or** B. With both, every skill is loaded twice.

### Option C — claude.ai (web / desktop app)

```bash
python tools/package_skills.py     # validates and writes dist/<skill>.zip
```

In claude.ai, go to **Settings → Capabilities → Skills → Upload skill** and upload each zip from `dist/`
(`abap-documentation.zip` **and** `abap-document-object.zip`, plus `abap-module-index.zip` if you want it).
On claude.ai you upload your abapGit repo as a zip into the chat. The skills then deliver `docs/` as a zip, and git steps are skipped.

---

## Using it on a project

1. Open Claude Code at the root of an abapGit repository (the folder holding the `<package>/src/` folders).
2. Ask, for example, *"Run a documentation pass on this repo"* or *"Document T-Code ZMM_042"*.
3. On the first pass Claude creates `docs/_methodology.md`. Check its **"Namespaces in scope"** list (Z, Y, plus any
   partner namespace your customer uses) — it decides what gets drilled.
4. `docs/_index/sap_standard.md` builds up as SAP-standard lookups are made. Commit it with the docs, so the next
   person reuses the lookups.
5. Review the docs. Claude proposes commits and only commits or pushes when you say so.

---

## Repository layout

```
.claude-plugin/          plugin.json + marketplace.json (Option A)
skills/
  abap-documentation/    SKILL.md, template, module-vocab, reading-grammars, reviewer prompt, scripts/
  abap-document-object/  SKILL.md
  abap-module-index/     SKILL.md, references/, scripts/, examples/
tools/
  install.ps1 / install.sh   copy-install (Option B)
  package_skills.py          validate + build claude.ai zips (Option C)
```

## Changing the skills

1. Edit the files under `skills/`.
2. If you change the **Drill-down hard rules**, make the same change in **both** `abap-documentation/SKILL.md` and
   `abap-document-object/SKILL.md`. The check in step 4 fails if the two copies differ.
3. Bump `metadata.version` in the skill's frontmatter, plus `version` in `.claude-plugin/plugin.json` and
   `marketplace.json`, and add a line to `CHANGELOG.md`.
4. Run `python tools/package_skills.py --check`. It enforces the claude.ai upload rules (frontmatter keys, a
   description of at most 1024 characters with no `<` `>`) and the hard-rules match.
5. Open a pull request.

## License

MIT — see [LICENSE](LICENSE).
