#!/usr/bin/env python3
"""
abap-documentation DOCX Renderer — Phase 5 of the methodology (optional).

For every `.md` file under `docs/`, ensure a parallel `.docx` exists under
`docs_docx/` with the same folder structure. Skips files whose `.docx`
is already newer than the source `.md` (incremental — only converts what
actually changed).

Uses pandoc as the rendering engine. Requires pandoc on PATH.

Usage:
    python render_docx.py [--repo-root .] [--docs docs] [--out docs_docx] [--force]

    --force   Re-render every file regardless of timestamp.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Render every docs/**/*.md to docs_docx/**/*.docx via pandoc.")
    ap.add_argument("--repo-root", default=".", help="Repo root.")
    ap.add_argument("--docs", default="docs", help="Markdown source directory (relative to repo-root).")
    ap.add_argument("--out", default="docs_docx", help="DOCX output directory (relative to repo-root).")
    ap.add_argument("--force", action="store_true", help="Re-render every file, ignore mtime.")
    args = ap.parse_args()

    if not shutil.which("pandoc"):
        print("ERROR: pandoc not found on PATH. Install from https://pandoc.org/installing.html", file=sys.stderr)
        return 2

    repo_root = Path(args.repo_root).resolve()
    docs_dir = (repo_root / args.docs).resolve()
    out_dir = (repo_root / args.out).resolve()

    if not docs_dir.exists():
        print(f"ERROR: docs dir not found: {docs_dir}", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    n_total = 0
    n_converted = 0
    n_skipped = 0
    n_failed = 0
    failures = []

    for md in sorted(docs_dir.rglob("*.md")):
        n_total += 1
        rel = md.relative_to(docs_dir)
        docx = (out_dir / rel).with_suffix(".docx")
        docx.parent.mkdir(parents=True, exist_ok=True)

        if not args.force and docx.exists() and docx.stat().st_mtime >= md.stat().st_mtime:
            n_skipped += 1
            continue

        try:
            subprocess.run(
                ["pandoc", "-f", "gfm", "-t", "docx", str(md), "-o", str(docx)],
                check=True,
                capture_output=True,
            )
            n_converted += 1
            print(f"  OK   {rel}")
        except subprocess.CalledProcessError as e:
            n_failed += 1
            failures.append((rel, e.stderr.decode("utf-8", errors="replace")))
            print(f"  FAIL {rel}: {e.stderr.decode('utf-8', errors='replace').strip()[:120]}", file=sys.stderr)

    print("")
    print(f"Total MD files: {n_total}")
    print(f"Converted:      {n_converted}")
    print(f"Skipped (up-to-date): {n_skipped}")
    print(f"Failed:         {n_failed}")

    if failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
