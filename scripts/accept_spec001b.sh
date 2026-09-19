#!/usr/bin/env bash
# Exact owner interpreter; every artifact stays in the ignored private run root.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null
run="runs/spec001b-owner-$(date -u +%Y%m%dT%H%M%SZ)-$$"
uv run --offline --frozen --python 3.12.14 python scripts/accept_spec001b.py --require-python 3.12.14 --output "$run"
printf 'WSL_SPEC001B_ACCEPTANCE_PASS; artifacts: %s\n' "$run"
