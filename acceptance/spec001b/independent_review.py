"""Run six controlled negative regressions in private isolated source copies.

No mutation touches the source checkout. Every chosen test first runs unchanged;
then a single check is disabled in a separate copied repository. Real nonzero
unittest results, executed method counts, exact test IDs and private log hashes
are the evidence. Neither import errors nor missing mutation sites count as PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
MUTATIONS = (
    {"id": "PORT_VALIDATION_REMOVED", "file": "rcwg_spec/operators.py",
     "before": 'if not set(names) <= set(inputs) or (not captures and set(inputs) != set(names)):',
     "after": 'if False:  # isolated negative-review mutation',
     "test_id": "test_spec001b_operators.TestOperatorContracts.test_all_branches_reject_wrong_input_and_output_ports"},
    {"id": "DECLARED_SCHEMA_TRUSTED", "file": "rcwg_spec/operators.py",
     "before": 'check_declared(actual, declared[port], path + "/outputs/" + _ptr(port))',
     "after": 'pass  # isolated negative-review mutation: declared schema no longer verified',
     "test_id": "test_spec001b_operators.TestOperatorContracts.test_projection_schema_is_derived_and_declarations_do_not_override"},
    {"id": "MISSING_EXPECTED_RECORD_SHRINKS_DENOMINATOR", "file": "rcwg_spec/binding.py",
     "before": 'model_expected = sum(r["record_role"] == "MODEL" for r in expected.values())',
     "after": 'model_expected = len(records)  # isolated negative-review mutation',
     "test_id": "test_spec001b_binding.BindingTests.test_missing_expected_record_does_not_shrink_denominator"},
    {"id": "CACHE_RUNTIME_SOURCE_BINDING_IGNORED", "file": "rcwg_spec/binding.py",
     "before": 'if record["context_hashes"] != {key: value for key, value in context.items() if key.endswith("_hash")}:',
     "after": 'if False:  # isolated negative-review mutation',
     "test_id": "test_spec001b_binding.BindingTests.test_cache_runtime_source_sidecar_tampering_rejected"},
    {"id": "PRIVATE_GOLD_PASSTHROUGH", "file": "rcwg_spec/generation.py",
     "before": 'checked = validate_public_task(task)',
     "after": 'checked = {"normalized_task": deepcopy(task), "task_input_hash": digest(task), "normalized_input_hash": digest(task)}',
     "test_id": "test_spec001b_generation.GenerationTests.test_private_canary_rejected_top_level_nested_and_unknown_key"},
    {"id": "REGION_OUTER_INPUT_SCOPE_BYPASSED", "file": "rcwg_spec/ir_structure.py",
     "before": 'fail("SCOPE_VIOLATION", p, "region inputs must be explicitly bound")',
     "after": 'pass  # isolated negative-review mutation: outer source admitted into region',
     "test_id": "test_spec001b_regions.TestCompilerControls.test_outer_source_cannot_bypass_region_binding"},
)

HARNESS = r'''
import io, json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "tests"))
requested = json.loads(sys.argv[1])
suite = unittest.defaultTestLoader.loadTestsFromNames(requested)
output = io.StringIO()
result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
Path(sys.argv[2]).write_text(output.getvalue(), encoding="utf8")
failed_ids = sorted({test.id().split(" (", 1)[0] for test, detail in result.failures})
error_ids = sorted({test.id().split(" (", 1)[0] for test, detail in result.errors})
report = {"tests_run": result.testsRun, "failures": len(result.failures),
          "errors": len(result.errors), "skipped": len(result.skipped),
          "failed_test_ids": failed_ids, "error_test_ids": error_ids,
          "count_semantics": "tests_run counts methods; failures/errors count unittest entries including subtests",
          "import_error": any("_FailedTest" in ident for ident in failed_ids + error_ids)}
print(json.dumps(report, sort_keys=True))
sys.exit(0 if result.wasSuccessful() else 1)
'''


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_checkout(destination):
    destination.mkdir()
    for name in ("rcwg_spec", "rcwg_boot", "tests", "specs", "prompts"):
        shutil.copytree(ROOT / name, destination / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _run(copy, test_ids, log_path):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # The subprocess must import only the isolated copy, not a caller's checkout.
    env.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, "-c", HARNESS, json.dumps(test_ids), str(log_path)],
                            cwd=copy, env=env, capture_output=True, timeout=60)
    process_log = log_path.with_suffix(".process.log")
    with process_log.open("xb") as stream:
        stream.write(result.stdout + b"\nSTDERR\n" + result.stderr)
    try:
        parsed = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError):
        parsed = {"tests_run": 0, "failures": 0, "errors": 1, "skipped": 0,
                  "failed_test_ids": [], "error_test_ids": [], "import_error": True}
    return {**parsed, "exit_code": result.returncode,
            "log_path": str(log_path.relative_to(ROOT)),
            "log_sha256": _sha(log_path) if log_path.is_file() else None,
            "process_log_sha256": _sha(process_log)}


def run_review():
    if sys.version_info[:3] != (3, 12, 14):
        return {"status": "NEGATIVE_REVIEW_BLOCKED", "reason": "Python 3.12.14 required",
                "python_version": sys.version.split()[0], "formal_ready": False}
    private = ROOT / "runs"
    private.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="spec001b-negative-review-", dir=private))
    baseline_copy = directory / "baseline"
    _copy_checkout(baseline_copy)
    test_ids = [row["test_id"] for row in MUTATIONS]
    baseline = _run(baseline_copy, test_ids, directory / "baseline.log")
    baseline_pass = (baseline["exit_code"] == 0 and baseline["tests_run"] == 6
                     and not baseline["import_error"] and not baseline["skipped"])
    outcomes = []
    for index, mutation in enumerate(MUTATIONS):
        copied = directory / ("mutation-" + str(index + 1))
        shutil.copytree(baseline_copy, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        target = copied / mutation["file"]
        original = target.read_text(encoding="utf8")
        count = original.count(mutation["before"])
        row = {"mutation_id": mutation["id"], "source_file": mutation["file"],
               "test_id": mutation["test_id"], "mutation_sites": count,
               "baseline_source_sha256": _sha(target), "detected": False}
        if count != 1:
            row["reason"] = "unique mutation site required"
            outcomes.append(row)
            continue
        target.write_text(original.replace(mutation["before"], mutation["after"], 1), encoding="utf8")
        row["mutated_source_sha256"] = _sha(target)
        executed = _run(copied, [mutation["test_id"]], directory / ("mutation-" + str(index + 1) + ".log"))
        row["result"] = executed
        row["detected"] = (executed["exit_code"] == 1 and executed["tests_run"] == 1
                           and executed["failures"] + executed["errors"] > 0
                           and not executed["import_error"] and not executed["skipped"])
        outcomes.append(row)
    source_files = sorted({item["file"] for item in MUTATIONS})
    unmodified = all(_sha(ROOT / name) == _sha(baseline_copy / name) for name in source_files)
    complete = baseline_pass and unmodified and all(row["detected"] for row in outcomes)
    return {"status": "NEGATIVE_REVIEW_PASS" if complete else "NEGATIVE_REVIEW_FAIL",
            "python_version": sys.version.split()[0], "baseline": baseline,
            "mutation_count": len(outcomes), "mutations_detected": sum(row["detected"] for row in outcomes),
            "mutations": outcomes, "source_checkout_unchanged": unmodified,
            "source_hashes": {name: _sha(ROOT / name) for name in source_files},
            "real_model_requests": 0, "formal_ready": False,
            "scope": "BOOT_ONLY controlled test sensitivity; not model failure frequencies"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_review()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "NEGATIVE_REVIEW_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
