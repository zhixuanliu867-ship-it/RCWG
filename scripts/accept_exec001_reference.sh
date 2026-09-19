#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="runs/exec001-reference-owner-$(date -u +%Y%m%dT%H%M%SZ)-$$"
uv run --offline --frozen --python 3.12.14 python scripts/accept_exec001_reference.py --output "$OUT"
printf 'Reference evidence: %s\nFull EXEC-001 still follows docs/exec001/ACCEPTANCE.md\n' "$OUT"
