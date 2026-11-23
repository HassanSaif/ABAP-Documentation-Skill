#!/usr/bin/env python3
"""
Validate every skill under skills/ and build one upload-ready zip per skill
in dist/ (for claude.ai > Settings > Capabilities > Skills > Upload skill).

Checks mirror what claude.ai enforces on upload:
  - exactly one SKILL.md, at the skill root, with YAML frontmatter
  - frontmatter keys limited to name / description / license /
    allowed-tools / metadata / compatibility
  - name is kebab-case, <= 64 chars, and matches the folder name
  - description is <= 1024 chars and contains no angle brackets

Also checks that the "Drill-down hard rules" block is identical in the
two skills that carry it.

Stdlib only.

Usage:
    python tools/package_skills.py            # validate + build dist/*.zip
    python tools/package_skills.py --check    # validate only
"""

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
DIST = ROOT / "dist"

ALLOWED_KEYS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
EXCLUDED_PARTS = {"__pycache__", "node_modules", ".git"}
EXCLUDED_SUFFIXES = (".pyc", ".bak")


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    if not m:
        raise ValueError("no YAML frontmatter")
    out = {}
    for line in m.group(1).splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def _packaged(path: Path, skill_dir: Path) -> bool:
    rel = path.relative_to(skill_dir)
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    return not (path.suffix in EXCLUDED_SUFFIXES or ".bak" in path.name)


def validate(skill_dir: Path) -> list[str]:
    errors = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return ["SKILL.md not found"]
    nested = [p for p in skill_dir.rglob("SKILL.md") if p != skill_md and _packaged(p, skill_dir)]
    if nested:
        errors.append(f"extra SKILL.md files: {', '.join(str(p.relative_to(skill_dir)) for p in nested)}")
    try:
        fm = _frontmatter(skill_md.read_text(encoding="utf-8"))
    except ValueError as e:
        return errors + [str(e)]
    unexpected = set(fm) - ALLOWED_KEYS
    if unexpected:
        errors.append(f"unexpected frontmatter keys: {', '.join(sorted(unexpected))}")
    name, desc = fm.get("name", ""), fm.get("description", "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append(f"bad name {name!r}")
    if name != skill_dir.name:
        errors.append(f"name {name!r} does not match folder {skill_dir.name!r}")
    if not desc:
        errors.append("missing description")
    if len(desc) > 1024:
        errors.append(f"description too long ({len(desc)} > 1024)")
    if "<" in desc or ">" in desc:
        errors.append("description contains angle brackets")
    return errors


HARD_RULES = re.compile(r"<!-- hard-rules:start.*?<!-- hard-rules:end -->", re.DOTALL)
HARD_RULES_SKILLS = ("abap-documentation", "abap-document-object")


def hard_rules_drift() -> list[str]:
    """The drill-down hard rules are pasted into two skills; they must not diverge."""
    blocks = {}
    for name in HARD_RULES_SKILLS:
        m = HARD_RULES.search((SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))
        if not m:
            return [f"{name}: hard-rules block missing"]
        blocks[name] = m.group(0)
    if len(set(blocks.values())) > 1:
        return [f"hard-rules block differs between {' and '.join(HARD_RULES_SKILLS)}"]
    return []


def build(skill_dir: Path) -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / f"{skill_dir.name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(skill_dir.rglob("*")):
            if p.is_file() and _packaged(p, skill_dir):
                zf.write(p, Path(skill_dir.name) / p.relative_to(skill_dir))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="Validate only; do not build zips.")
    args = ap.parse_args()

    failed = False
    for e in hard_rules_drift():
        failed = True
        print(f"FAIL  {e}")
    for skill_dir in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
        errors = validate(skill_dir)
        if errors:
            failed = True
            print(f"FAIL  {skill_dir.name}")
            for e in errors:
                print(f"        - {e}")
            continue
        if args.check:
            print(f"OK    {skill_dir.name}")
        else:
            print(f"OK    {skill_dir.name}  ->  {build(skill_dir).relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
