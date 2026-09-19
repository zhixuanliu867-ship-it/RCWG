"""Regression tests for issues reproduced during owner-WSL import review."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rcwg_spec.common import ContractError, load
from rcwg_spec.metrology import score_repeat
from test_spec001a import fixture

ROOT = Path(__file__).resolve().parents[1]


class TestStrictJsonReview(unittest.TestCase):
    def test_overflowing_exponents_are_rejected_recursively(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'input.json'
            for raw in ('1e400', '-1e400', '{"nested": [1e400]}'):
                with self.subTest(raw=raw):
                    path.write_text(raw, encoding='utf8')
                    with self.assertRaisesRegex(ContractError, 'INVALID_NUMBER'):
                        load(path)

    def test_finite_signed_exponents_remain_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'input.json'
            path.write_text('[-1e3, 1.5e2, 1e-3]', encoding='utf8')
            self.assertEqual(load(path), [-1000.0, 150.0, .001])


class TestScoreCliReview(unittest.TestCase):
    def assert_cli_rejects(self, payload, code):
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d) / 'input.json', Path(d) / 'result.json'
            source.write_text(json.dumps(payload), encoding='utf8')
            result = subprocess.run(
                [sys.executable, '-m', 'rcwg_spec', 'score', str(source), '--output', str(output)],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stderr, '')
            error = json.loads(result.stdout)
            self.assertEqual(error['status'], 'SPEC_ERROR')
            self.assertEqual(error['code'], code)
            self.assertFalse(error['formal_ready'])
            self.assertFalse(output.exists())

    def test_non_objects_return_structured_error_without_output(self):
        for payload in (None, 42, 'text', [], [{'manifest': []}]):
            with self.subTest(payload=payload):
                self.assert_cli_rejects(payload, 'OBJECT_REQUIRED')

    def test_missing_fixture_fields_return_structured_error(self):
        self.assert_cli_rejects({'fixture_scope': 'ENGINEERING_ONLY'}, 'MISSING_FIELD')

    def test_unknown_fixture_field_is_not_silently_ignored(self):
        payload = load(ROOT / 'specs/spec001a/examples/synthetic_ledger.json')
        payload['unexpected'] = 'engineering-canary'
        self.assert_cli_rejects(payload, 'UNKNOWN_FIELD')

    def test_non_engineering_scope_stays_blocked(self):
        payload = load(ROOT / 'specs/spec001a/examples/synthetic_ledger.json')
        payload['fixture_scope'] = 'FORMAL'
        self.assert_cli_rejects(payload, 'ENGINEERING_SCOPE')


class TestCompletionTimeReview(unittest.TestCase):
    def test_aborted_run_elapsed_time_is_not_a_completion_ratio(self):
        for status in ('TIMEOUT', 'OOM', 'EXECUTION_ERROR', 'INVALID_PLAN', 'REFUSAL', 'TASK_FAILURE'):
            with self.subTest(status=status):
                expected, observed, reference = fixture()
                observed.update(status=status, semantic_pass=False, reason='synthetic termination')
                result = score_repeat(expected, observed, reference)
                self.assertIsNone(result['time_ratio'])
                self.assertFalse(result['efficient_success'])

    def test_infrastructure_elapsed_time_does_not_imply_completion(self):
        for status in ('INFRA_FAILURE', 'CANCELLED', 'MISSING_EVIDENCE'):
            with self.subTest(status=status):
                expected, observed, reference = fixture()
                observed.update(status=status, semantic_pass=None, reason='synthetic missing completion')
                result = score_repeat(expected, observed, reference)
                self.assertIsNone(result['time_ratio'])
                self.assertIsNone(result['efficient_success'])

    def test_completed_run_ratio_and_threshold_are_preserved(self):
        expected, observed, reference = fixture()
        observed['metrics']['wall_s']['value'] = 1.2
        result = score_repeat(expected, observed, reference)
        self.assertEqual(result['time_ratio'], 1.2)
        self.assertTrue(result['efficient_success'])


class TestPublicGuardReview(unittest.TestCase):
    def run_guard(self, name, staged_content, worktree_content=None, delete_worktree=False):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'scripts').mkdir()
            shutil.copyfile(ROOT / 'scripts/check_public_tree.py', root / 'scripts/check_public_tree.py')
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(staged_content, encoding='utf8')
            subprocess.run(['git', '-C', str(root), 'add', '--', name], check=True, capture_output=True)
            if worktree_content is not None:
                target.write_text(worktree_content, encoding='utf8')
            if delete_worktree:
                target.unlink()
            return subprocess.run([sys.executable, str(root / 'scripts/check_public_tree.py')],
                                  capture_output=True, text=True)

    def test_github_token_shapes_are_blocked_without_echoing_content(self):
        for value in ('gh' + 'p_' + 'X' * 36, 'github_' + 'pat_' + 'X' * 80):
            result = self.run_guard('sample.txt', value)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('possible credential pattern', result.stderr)
            self.assertNotIn(value, result.stdout + result.stderr)

    def test_private_runs_and_venv_cannot_be_published(self):
        for name in ('runs/example.json', '.venv/pyvenv.cfg'):
            result = self.run_guard(name, 'synthetic')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('private path is tracked', result.stderr)

    def test_guard_checks_staged_bytes_even_after_worktree_is_cleaned(self):
        value = 'gh' + 'p_' + 'X' * 36
        result = self.run_guard('sample.txt', value, 'redacted worktree')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(value, result.stdout + result.stderr)

    def test_safe_public_file_passes(self):
        self.assertEqual(self.run_guard('sample.txt', 'ordinary public text').returncode, 0)

    def test_deleted_worktree_file_cannot_hide_staged_token(self):
        value = 'gh' + 'p_' + 'X' * 36
        result = self.run_guard('sample.txt', value, delete_worktree=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(value, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
