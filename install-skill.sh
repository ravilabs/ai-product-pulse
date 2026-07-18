#!/usr/bin/env bash
# Stages the AI Product Pulse skill for a given harness.
#
# Usage:
#   ./install-skill.sh <harness> [--global]
#
#   <harness>   One of: claude-code, cursor, openclaw, hermes
#   --global    Stage to the harness's global/user directory instead of
#               the current project. Ignored for claude-code and cursor,
#               which are always project-scoped by this script (use their
#               own ~/.claude/skills or ~/.cursor/skills by hand if you
#               want personal-scope instead of project-scope).
#
# Always copies from the canonical skills/ai-product-pulse/SKILL.md —
# never edit a staged copy directly, it'll just drift from the source
# and the parity test in the repo will start failing.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANONICAL="$SCRIPT_DIR/skills/ai-product-pulse/SKILL.md"

usage() {
  cat <<EOF
Usage: $(basename "$0") <harness> [--global]

  harness   claude-code | cursor | openclaw | hermes
  --global  Stage to the harness's global skills directory (openclaw,
            hermes only) instead of the current project.

Examples:
  $(basename "$0") claude-code
  $(basename "$0") hermes --global
EOF
  exit 1
}

[ -f "$CANONICAL" ] || { echo "Canonical skill not found at $CANONICAL" >&2; exit 1; }
[ $# -ge 1 ] || usage

HARNESS="$1"
SCOPE="${2:-}"

case "$HARNESS" in
  claude-code)
    DEST=".claude/skills/ai-product-pulse"
    ;;
  cursor)
    DEST=".cursor/skills/ai-product-pulse"
    ;;
  openclaw)
    if [ "$SCOPE" = "--global" ]; then
      DEST="$HOME/.openclaw/skills/ai-product-pulse"
    else
      DEST="skills/ai-product-pulse"
    fi
    ;;
  hermes)
    if [ "$SCOPE" = "--global" ]; then
      DEST="$HOME/.hermes/skills/ai-product-pulse"
    else
      DEST="skills/ai-product-pulse"
    fi
    ;;
  *)
    echo "Unknown harness: '$HARNESS'" >&2
    usage
    ;;
esac

mkdir -p "$DEST"
cp "$CANONICAL" "$DEST/SKILL.md"
echo "Staged AI Product Pulse -> $DEST/SKILL.md"

if [ "$HARNESS" = "claude-code" ] || [ "$HARNESS" = "cursor" ]; then
  echo "Also wire up the MCP server — see mcp/${HARNESS}-mcp.json.example (requires the package installed first: pip install -e packages/python)"
elif [ "$HARNESS" = "openclaw" ]; then
  echo "Or skip this script and run: clawhub install ravilabs/ai-product-pulse"
elif [ "$HARNESS" = "hermes" ]; then
  echo "Or skip this script and run: hermes skills tap add ravilabs/ai-product-pulse"
fi
