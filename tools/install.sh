#!/usr/bin/env bash
# Install the ABAP documentation skills into Claude Code by copying them.
#
#   ./tools/install.sh            # personal: ~/.claude/skills
#   ./tools/install.sh --project  # this project: ./.claude/skills
#
# An existing copy is moved to ~/.claude/skills-backup/<name>-<timestamp> first;
# backups live outside the skills folder so Claude Code does not load them as
# duplicate skills. Prefer the plugin install (see README) for /plugin updates.
set -euo pipefail

src="$(cd "$(dirname "$0")/../skills" && pwd)"
if [[ "${1:-}" == "--project" ]]; then
  target="$PWD/.claude/skills"
else
  target="$HOME/.claude/skills"
fi
backup_root="$HOME/.claude/skills-backup"
stamp="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$target"
for dir in "$src"/*/; do
  name="$(basename "$dir")"
  dest="$target/$name"
  if [[ -e "$dest" ]]; then
    mkdir -p "$backup_root"
    mv "$dest" "$backup_root/$name-$stamp"
    echo "  backed up existing $name -> $backup_root/$name-$stamp"
  fi
  cp -R "$dir" "$dest"
  find "$dest" \( -name '__pycache__' -o -name '*.pyc' \) -prune -exec rm -rf {} +
  echo "  installed $name -> $dest"
done

echo
echo "Done. Restart Claude Code (or start a new session) to pick up the skills."
