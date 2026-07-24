#!/usr/bin/env bash
# Create (or enter) a prototype dir and drop into an auto-mode Claude session there.
# Usage: bun run prototype <name>
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: bun run prototype <name>" >&2
  exit 1
fi

mvp_root="$(cd "$(dirname "$0")/.." && pwd)"
dir="$mvp_root/prototypes/$1"

mkdir -p "$dir"
cd "$dir"
exec claude --permission-mode auto
