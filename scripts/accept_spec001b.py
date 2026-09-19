#!/usr/bin/env python3
"""Complete offline SPEC-001B gate; sentinels alone can never pass this gate."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def source_files():
    paths = [p for folder in ('rcwg_boot', 'rcwg_spec', 'tests', 'scripts', 'acceptance/spec001b', 'specs/spec001b')
             for p in sorted((ROOT / folder).rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    return paths + [ROOT / '.github/workflows/ci.yml']


def source_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files()}


def staged_sources_match():
    entries = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT).split(b'\0')
    index = {}
    for entry in entries:
        if entry:
            metadata, path = entry.split(b'\t', 1)
            mode, oid, stage = metadata.split()
            if stage == b'0':
                index[path.decode('utf8')] = oid.decode()
    algorithm = subprocess.check_output(['git', 'rev-parse', '--show-object-format'], cwd=ROOT, text=True).strip()
    mismatches = []
    for path in source_files():
        data = path.read_bytes()
        oid = hashlib.new(algorithm, b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if index.get(str(path.relative_to(ROOT))) != oid:
            mismatches.append(str(path.relative_to(ROOT)))
    return mismatches


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed_ids, self.failed_ids, self.skipped_ids = [], set(), []
        self.subcase_count = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        if test.id() not in self.failed_ids:
            self.passed_ids.append(test.id())

    def addError(self, test, err):
        super().addError(test, err)
        self.failed_ids.add(test.id())

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.failed_ids.add(test.id())

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.skipped_ids.append(test.id())

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.subcase_count += 1
        if err:
            self.failed_ids.add(test.id())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-python', default=None)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'SPEC001B_IN_PROGRESS', 'python_version': platform.python_version(),
              'system': platform.system(), 'formal_ready': False,
              'runtime_kernel_status': 'NOT_IMPLEMENTED', 'commands': []}
    failures = []
    initial_sources = source_hashes()
    report['unstaged_or_untracked_sources'] = staged_sources_match()
    if report['unstaged_or_untracked_sources']:
        failures.append('UNTRACKED_OR_DIFFERENT_STAGED_SOURCE_BYTES')
    immutable = {
        'tests/test_spec001a_review.py': '659d2c75b54c259f34d21a6c1f34eb3b614b0da6991fcc1f643a1f570912b9d9',
        'tests/test_spec001a.py': 'a8347cd23210c1cfc8f360f5176f371e06f9c243fc2d20318963380926bc1fc3',
        'tests/test_core.py': '0b86c434685a6e33fd26bf97fc1691e4da034cd000b1c2343e218a2196d1bbd3',
        'tests/test_spec001b_foundation.py': 'a62139294f2d72379438093e11daa60ee6f1bf9172eccb1044b65caf965b5bbf',
        'acceptance/spec001b/compiler_cases.json': 'e700ad2ad52627fe6879b90997515100f4ac288bd7b4a93c43dadd96c2cd65dc',
    }
    report['protected_foundation'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                      for name in immutable}
    if report['protected_foundation'] != immutable:
        failures.append('FOUNDATION_OR_SENTINELS_CHANGED')
    unstaged = subprocess.run(['git', 'diff', '--quiet'], cwd=ROOT)
    if unstaged.returncode:
        failures.append('STAGED_CONTENT_DIFFERS_FROM_TESTED_WORKTREE')
    if args.require_python and platform.python_version() != args.require_python:
        failures.append('TARGET_PYTHON_MISMATCH')
    if not ((3, 12) <= sys.version_info[:2] < (3, 14)):
        failures.append('UNSUPPORTED_PYTHON')
    with (output / 'unittest.txt').open('x', encoding='utf8') as log:
        suite = unittest.TestLoader().discover(str(ROOT / 'tests'))
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=EvidenceResult).run(suite)
    report['tests'] = {'methods_run': result.testsRun, 'passed_ids': result.passed_ids,
                       'failed_ids': sorted(result.failed_ids), 'skipped_ids': result.skipped_ids,
                       'subcases_run': result.subcase_count,
                       'expected_failure_ids': [test.id() for test, _ in result.expectedFailures],
                       'subcases_are_additional_methods': False}
    report['commands'].append({'command': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                               'execution': 'equivalent unittest runner with per-method evidence',
                               'exit_code': 0 if result.wasSuccessful() else 1, 'stdout_stderr': 'unittest.txt'})
    if not result.wasSuccessful() or result.skipped_ids or result.expectedFailures:
        failures.append('UNITTEST_FAILED_OR_SKIPPED')
    required_ids = json.loads((ROOT / 'specs/spec001b/required_test_ids.json').read_text())['required_test_ids']
    report['missing_required_test_ids'] = sorted(set(required_ids) - set(result.passed_ids))
    if len(required_ids) != len(set(required_ids)) or report['missing_required_test_ids']:
        failures.append('REQUIRED_TEST_METHODS_MISSING')
    # Explicitly retain the old and foundation method sets, not just a total count.
    for module, expected in (('test_core.', 43), ('test_spec001a.', 74),
                             ('test_spec001a_review.', 14), ('test_spec001b_foundation.', 63)):
        if sum(t.startswith(module) for t in result.passed_ids) != expected:
            failures.append('REQUIRED_BASELINE_TESTS_NOT_PRESERVED:' + module)
    try:
        from rcwg_spec.coverage import contract_coverage, acceptance_test_coverage
        matrix = contract_coverage(result.passed_ids, failed_test_ids=result.failed_ids,
                                   skipped_test_ids=result.skipped_ids)
        (output / 'contract-coverage.json').write_text(json.dumps(matrix, indent=2) + '\n')
        report['coverage'] = {'status': matrix['status'], 'operators': matrix['operator_count'],
                              'implementation_branches': matrix['implementation_branch_count'],
                              'static_implementation_gaps': matrix['static_implementation_gaps']}
        report['acceptance_matrix'] = acceptance_test_coverage(result.passed_ids)
    except Exception as exc:
        failures.append('CONTRACT_COVERAGE_FAILED:' + type(exc).__name__)

    checks = [
        ('boot', ['-m', 'rcwg_boot', 'check'], 0, 'BOOT_CHECK_PASS'),
        ('spec001a', ['-m', 'rcwg_spec', 'check'], 0, 'SPEC001A_CORE_PASS'),
        ('smoke', ['-m', 'rcwg_boot', 'smoke'], 0, 'PASS'),
        ('mock-api', ['-m', 'rcwg_boot', 'api-probe'], 0, 'PASS'),
        ('formal', ['-m', 'rcwg_boot', 'check', '--formal'], 2, 'BLOCKED_NOT_FROZEN'),
        ('sentinels', ['acceptance/spec001b/run_compiler_sentinels.py'], 0, 'SPEC001B_SENTINELS_PASS'),
        ('negative-review', ['acceptance/spec001b/independent_review.py'], 0, 'NEGATIVE_REVIEW_PASS'),
        ('public-guard', ['scripts/check_public_tree.py'], 0, None),
        ('compile', ['-m', 'compileall', '-q', 'rcwg_boot', 'rcwg_spec', 'scripts', 'tests', 'acceptance/spec001b'], 0, None),
    ]
    for name, argv, expected_exit, status in checks:
        command = [sys.executable, *argv]
        run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        (output / (name + '.stdout.txt')).write_text(run.stdout, encoding='utf8')
        (output / (name + '.stderr.txt')).write_text(run.stderr, encoding='utf8')
        entry = {'command': command, 'exit_code': run.returncode, 'expected_exit_code': expected_exit,
                 'stdout': name + '.stdout.txt', 'stderr': name + '.stderr.txt'}
        report['commands'].append(entry)
        if run.returncode != expected_exit:
            failures.append(name + ':EXIT_CODE')
        if status:
            try:
                parsed = json.loads(run.stdout)
                if parsed['status'] != status:
                    failures.append(name + ':STATUS')
                if name == 'sentinels' and (parsed['tested_cases'], parsed['passed_cases']) != (27, 27):
                    failures.append('SENTINEL_COUNT')
                if name == 'negative-review':
                    report['negative_review'] = parsed
                    for i, entry in enumerate([parsed['baseline'], *[row['result'] for row in parsed['mutations']]]):
                        original_log = ROOT / entry['log_path']
                        if not original_log.resolve().is_relative_to((ROOT / 'runs').resolve()):
                            raise ValueError('private review log escapes run directory')
                        for source, suffix, hash_key in ((original_log, 'unittest', 'log_sha256'),
                                                        (original_log.with_suffix('.process.log'), 'process', 'process_log_sha256')):
                            content = source.read_bytes()
                            if hashlib.sha256(content).hexdigest() != entry[hash_key]:
                                raise ValueError('review log hash mismatch')
                            (output / f'negative-review-{i}-{suffix}.txt').write_bytes(content)
                if name == 'mock-api':
                    evidence_path = ROOT / parsed['report']
                    probe = json.loads(evidence_path.read_text())
                    if probe['api_requests'] != 0 or probe['provider'] != 'mock':
                        failures.append('REAL_REQUESTS_FORBIDDEN')
                    (output / 'mock-api-report.json').write_bytes(evidence_path.read_bytes())
                if name == 'smoke':
                    (output / 'smoke-report.json').write_bytes((ROOT / parsed['report']).read_bytes())
            except Exception as exc:
                failures.append(name + ':BAD_REPORT:' + type(exc).__name__)
    syntax = subprocess.run(['bash', '-n', 'scripts/accept_spec001b.sh'], cwd=ROOT, capture_output=True, text=True)
    (output / 'bash-syntax.stdout.txt').write_text(syntax.stdout, encoding='utf8')
    (output / 'bash-syntax.stderr.txt').write_text(syntax.stderr, encoding='utf8')
    report['commands'].append({'command': ['bash', '-n', 'scripts/accept_spec001b.sh'], 'exit_code': syntax.returncode,
                               'stdout': 'bash-syntax.stdout.txt', 'stderr': 'bash-syntax.stderr.txt'})
    if syntax.returncode:
        failures.append('BASH_SYNTAX')
    report.setdefault('acceptance_matrix', []).extend([
        {'gate': 'B13', 'status': 'PASS' if not any(f.startswith(('sentinels', 'SENTINEL', 'FOUNDATION')) for f in failures) else 'FAIL',
         'evidence': 'sentinels.stdout.txt', 'cases_required': 27},
        {'gate': 'B14', 'status': 'PASS' if not failures else 'FAIL',
         'evidence': 'commands; unittest.txt; source_sha256', 'scope': 'this environment only; CI independently required'},
        {'gate': 'B15', 'status': 'REQUIRES_DELIVERY_ATTESTATION',
         'evidence_required': ['final patch clean apply and tree match', 'WSL and independent CI logs', 'SHA256', 'EXEC interface card']},
    ])
    report['source_sha256'] = source_hashes()
    if initial_sources != report['source_sha256'] or staged_sources_match():
        failures.append('SOURCE_CHANGED_DURING_ACCEPTANCE')
    report['git_head_at_test'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report['staged_tree_at_test'] = subprocess.check_output(['git', 'write-tree'], cwd=ROOT, text=True).strip()
    report['log_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}
    report['failures'] = failures
    report['status'] = 'SPEC001B_OFFLINE_GATES_PASS' if not failures else 'SPEC001B_IN_PROGRESS'
    report['real_model_requests'] = 0
    report['cloud_resource_mutations'] = 0
    report['iam_mutations'] = 0
    (output / 'ACCEPTANCE.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'methods_run': result.testsRun, 'failures': failures,
                      'formal_ready': False, 'runtime_kernel_status': 'NOT_IMPLEMENTED'}, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
