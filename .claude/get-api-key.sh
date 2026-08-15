#!/usr/bin/env bash
# Prints the Anthropic API key for Claude Code's apiKeyHelper.
#
# Reads from the repo's .env so the key lives in exactly one place — .env is
# already gitignored, and nothing here duplicates it into a second file.
set -euo pipefail

env_file="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env"

if [[ ! -f "$env_file" ]]; then
  echo "get-api-key.sh: no .env at $env_file" >&2
  exit 1
fi

key="$(grep -E '^ANTHROPIC_API_KEY=' "$env_file" | head -n1 | cut -d= -f2- | tr -d '"'"'"' \r')"

if [[ -z "$key" ]]; then
  echo "get-api-key.sh: ANTHROPIC_API_KEY is empty in $env_file" >&2
  exit 1
fi

printf '%s' "$key"
