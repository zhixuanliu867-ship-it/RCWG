#!/usr/bin/env bash
# Foundation acceptance only. The complete compiler is a separate pending gate.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null
RUN_DIR="$(mktemp -d "${PWD}/runs/spec001b-foundation-XXXXXX" 2>/dev/null || true)"
if [[ -z "$RUN_DIR" ]]; then
  mkdir -p runs
  RUN_DIR="$(mktemp -d "${PWD}/runs/spec001b-foundation-XXXXXX")"
fi
PY=(uv run --offline --frozen --python 3.12.14 python)
"${PY[@]}" -c 'import sys; assert sys.version_info[:3] == (3,12,14); print(sys.version)' > "$RUN_DIR/python.txt"
git rev-parse HEAD > "$RUN_DIR/git-head.txt"
git status --short > "$RUN_DIR/worktree-status.txt"
"${PY[@]}" -m unittest discover -s tests -v > "$RUN_DIR/unittest.txt" 2>&1
"${PY[@]}" -m rcwg_boot check > "$RUN_DIR/boot-check.json"
"${PY[@]}" -m rcwg_spec check > "$RUN_DIR/spec001a-check.json"
"${PY[@]}" -m rcwg_boot smoke > "$RUN_DIR/smoke.json"
"${PY[@]}" -m rcwg_boot api-probe > "$RUN_DIR/mock-api.json"
set +e
"${PY[@]}" -m rcwg_boot check --formal > "$RUN_DIR/formal-gate.json"
FORMAL_STATUS=$?
"${PY[@]}" acceptance/spec001b/run_compiler_sentinels.py --output "$RUN_DIR/compiler-sentinels.json" > "$RUN_DIR/compiler-sentinels.stdout.json"
SENTINEL_STATUS=$?
set -e
[[ "$FORMAL_STATUS" -eq 2 ]]
# The starter lacks a compiler and therefore yields 2. After implementation this
# becomes 0. A genuine sentinel failure (1) always fails this script.
[[ "$SENTINEL_STATUS" -eq 2 || "$SENTINEL_STATUS" -eq 0 ]]
"${PY[@]}" scripts/check_public_tree.py > "$RUN_DIR/public-guard.txt"
"${PY[@]}" -m compileall -q rcwg_spec tests acceptance/spec001b
printf 'SPEC001B_FOUNDATION_PASS\nfull SPEC001B acceptance remains separate.\nLogs: %s\n' "$RUN_DIR"
