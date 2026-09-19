#!/usr/bin/env bash
# Run from the repository root after applying the patch. No cloud or model requests.
set -euo pipefail
[[ -f pyproject.toml && -d rcwg_spec && -d tests ]] || { echo "Run from RCWG repository root." >&2; exit 2; }
command -v uv >/dev/null || { echo "uv must already be installed." >&2; exit 2; }
out="runs/spec001a-owner-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$out"
runpy() { uv run --offline --frozen --python 3.12.14 python "$@"; }
runpy -c 'import sys; print(sys.version); assert sys.version_info[:3] == (3,12,14)' | tee "$out/python.txt"
runpy -m unittest discover -s tests -v > "$out/unittest.txt" 2>&1
runpy -m rcwg_boot check > "$out/boot-check.json"
runpy -m rcwg_boot smoke > "$out/boot-smoke.json"
runpy -m rcwg_boot api-probe > "$out/mock-api.json"
set +e
runpy -m rcwg_boot check --formal > "$out/formal-gate.json"
status=$?
set -e
[[ "$status" -eq 2 ]] || { echo "Formal gate had unexpected exit: $status" >&2; exit 2; }
runpy -m rcwg_spec check > "$out/spec-check.json"
runpy -m rcwg_spec validate-task specs/reference_v1_0/examples/task_input.json > "$out/task-check.json"
runpy -m rcwg_spec demo --output "$out/synthetic-score.json" > "$out/synthetic-stdout.json"
runpy scripts/check_public_tree.py > "$out/public-guard.txt"
git rev-parse HEAD > "$out/git-head.txt"
git diff --stat > "$out/worktree-diff-stat.txt"
echo "OWNER_SPEC001A_ACCEPTANCE_PASS; artifacts: $out"
tail -5 "$out/unittest.txt"
