import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rcwg_boot.api_probe import endpoint, probe
from rcwg_boot.budget import reserve
from rcwg_boot.checks import ROOT, check, formal_gate
from rcwg_boot.common import canonical, digest, write_json
from rcwg_boot.doctor import collect
from rcwg_boot.smoke import compute, fixture, run, verify
from rcwg_boot import cloud
from rcwg_boot.net import NoRedirect

# Any accidental test network connection is a failing test.
def setUpModule():
    global no_network
    no_network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden in tests'))
    no_network.start()
def tearDownModule():
    no_network.stop()

class Serialization(unittest.TestCase):
    def test_canonical_order(self):
        self.assertEqual(digest({'a': 1, 'b': 2}), digest({'b': 2, 'a': 1}))
    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError): canonical({'x': float('nan')})
    def test_evidence_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'report.json'; write_json(p, {'ok': True})
            with self.assertRaises(FileExistsError): write_json(p, {'ok': False})

class Smoke(unittest.TestCase):
    def test_fixed_expected(self):
        result = compute(fixture())
        self.assertTrue(verify(fixture(), result))
        self.assertEqual(len(result), 5)
    def test_no_mutation(self):
        rows = fixture(); original = copy.deepcopy(rows); compute(rows)
        self.assertEqual(rows, original)
    def test_filter_before_topk(self):
        rows = [{'id': 0, 'score': 100, 'eligible': False}, {'id': 1, 'score': 1, 'eligible': True}]
        self.assertEqual(compute(rows, 1), [{'id': 1, 'score': 1}])
    def test_tie_break(self):
        rows = [{'id': i, 'score': 9, 'eligible': True} for i in (3, 2, 1)]
        self.assertEqual(compute(rows, 2), [{'id': 1, 'score': 9}, {'id': 2, 'score': 9}])
    def test_empty(self): self.assertEqual(compute([], 5), [])
    def test_k_zero(self): self.assertEqual(compute(fixture(), 0), [])
    def test_k_large(self): self.assertTrue(verify(fixture(), compute(fixture(), 999), 999))
    def test_negative_k(self):
        with self.assertRaises(ValueError): compute(fixture(), -1)
    def test_bool_k_rejected(self):
        with self.assertRaises(ValueError): compute(fixture(), True)
    def test_verifier_detects_change(self):
        self.assertFalse(verify(fixture(), [{'id': -1, 'score': 100}]))
    def test_fixture_hash_stable_across_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            a, pa = run(Path(td)); b, pb = run(Path(td))
            self.assertEqual(a['output_sha256'], b['output_sha256'])
            self.assertNotEqual(pa, pb)
            self.assertIsNone(a['remote_model_gpu_ns'])
            self.assertFalse(a['formal_result'])
            self.assertEqual(a['api_requests'], 0)
    def test_multiple_small_inputs(self):
        for n in range(30):
            rows = [{'id': i, 'score': (i * 13) % 7, 'eligible': i % 4 != 0} for i in range(n)]
            for k in (0, 1, 5, 40): self.assertTrue(verify(rows, compute(rows, k), k))

class Environment(unittest.TestCase):
    @patch('rcwg_boot.doctor._command_status', return_value='NOT_INSTALLED')
    def test_report_sanitized(self, _):
        with patch.dict(os.environ, {'SENTINEL_API_KEY': 'do-not-publish-this-secret'}):
            report = collect()
        text = json.dumps(report)
        self.assertNotIn('do-not-publish-this-secret', text)
        self.assertNotIn('hostname', report)
        self.assertNotIn('username', report)
        self.assertFalse(report['credentials_probed'])
        self.assertFalse(report['formal_ready'])
    def test_boot_integrity(self):
        r = check(); self.assertEqual(r['reference_files_verified'], 33)
        self.assertEqual((r['operators'], r['templates']), (32, 72))
    def test_formal_gate_blocked(self):
        self.assertEqual(formal_gate()['status'], 'BLOCKED_NOT_FROZEN')
    def test_changed_safety_config_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'configs').mkdir()
            cfg = json.loads((ROOT / 'configs/boot.json').read_text()); cfg['job']['max_retries'] = 3
            (root / 'configs/boot.json').write_text(json.dumps(cfg))
            with self.assertRaises(ValueError): check(root)
    def test_reference_tampering_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ('configs', 'provenance', 'specs', 'prompts'):
                shutil.copytree(ROOT / name, root / name)
            (root / 'specs/reference_v1_0/README.md').write_text('tampered')
            with self.assertRaises(ValueError): check(root)

class Budget(unittest.TestCase):
    def test_five_calls_then_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'ledger.sqlite3'
            for _ in range(5): reserve(p, '0.20')
            with self.assertRaises(ValueError): reserve(p, '0.01')
    def test_invalid_reservations(self):
        with tempfile.TemporaryDirectory() as td:
            for v in ('0', '-1', '0.21', 'NaN', 'Infinity', 'oops'):
                with self.subTest(v=v), self.assertRaises(ValueError): reserve(Path(td) / 'ledger', v)
    def test_restart_preserves_gate(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'ledger'
            rid = reserve(p, '0.10')
            with sqlite3.connect(p) as con:
                row = con.execute('SELECT micro_usd,status FROM reservations WHERE id=?', (rid,)).fetchone()
            self.assertEqual(row, (100000, 'RESERVED'))

    def test_concurrent_admission_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'ledger'
            def attempt(_):
                try:
                    reserve(p, '0.20')
                    return True
                except ValueError:
                    return False
            with ThreadPoolExecutor(max_workers=6) as pool:
                accepted = list(pool.map(attempt, range(12)))
            self.assertEqual(sum(accepted), 5)
            with sqlite3.connect(p) as con:
                self.assertEqual(con.execute('SELECT COUNT(*),SUM(micro_usd) FROM reservations').fetchone(), (5, 1000000))

class Endpoints(unittest.TestCase):
    def test_gemini_endpoint(self):
        self.assertIn('gemini-3.1-flash-lite:generateContent', endpoint('gemini', 'gemini-3.1-flash-lite', None))
    def test_workspace_endpoint(self):
        self.assertTrue(endpoint('dashscope', 'qwen-plus', 'https://123.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1').endswith('/chat/completions'))
    def test_legacy_endpoint(self):
        self.assertIn('dashscope-intl.aliyuncs.com', endpoint('dashscope', 'qwen-plus', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'))
    def test_bad_endpoint(self):
        urls = ['http://dashscope-intl.aliyuncs.com/compatible-mode/v1',
                'https://evil.example/compatible-mode/v1',
                'https://dashscope-intl.aliyuncs.com.evil.example/compatible-mode/v1',
                'https://user:password@dashscope-intl.aliyuncs.com/compatible-mode/v1',
                'https://dashscope-intl.aliyuncs.com/compatible-mode/v1?key=oops',
                'https://dashscope-intl.aliyuncs.com:444/compatible-mode/v1']
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError): endpoint('dashscope', 'qwen-plus', url)
    def test_bad_model_id(self):
        with self.assertRaises(ValueError): endpoint('gemini', '../evil', None)
    def test_redirect_denied(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example'))

class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key', 'DASHSCOPE_API_KEY': 'test-key',
                                         'CLOUD_RUN_EXECUTION': '', 'CLOUD_RUN_JOB': ''})
        self.env.start()
    def tearDown(self): self.env.stop(); self.tmp.cleanup()
    def call(self, provider='gemini', **kwargs):
        options = {'allow_paid': True, 'reserve_usd': '0.10', 'ledger': self.root/'ledger'}
        options.update(kwargs)
        return probe(provider, 'test-model', self.root/'runs', **options)
    def response(self, text='{"ok": true}'):
        return {'candidates': [{'content': {'parts': [{'text': text}]}}],
                'modelVersion': 'test-version', 'usageMetadata': {'promptTokenCount': 25, 'candidatesTokenCount': 5}}
    def test_mock_no_network(self):
        with patch('rcwg_boot.net.request_json') as call:
            report, _ = probe('mock', 'anything', self.root)
        call.assert_not_called(); self.assertEqual(report['api_requests'], 0)
    def test_paid_requires_opt_in(self):
        with self.assertRaises(ValueError): probe('gemini', 'test-model', self.root)
    def test_cloud_live_probe_blocked(self):
        with patch.dict(os.environ, {'CLOUD_RUN_EXECUTION': 'execution-test'}):
            with self.assertRaises(ValueError): self.call()
    def test_missing_key_blocked_before_reserving(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            with self.assertRaises(ValueError): self.call()
        self.assertFalse((self.root/'ledger').exists())
    def test_gemini_one_request(self):
        with patch('rcwg_boot.net.request_json', return_value=self.response()) as call:
            report, path = self.call()
        call.assert_called_once()
        self.assertEqual(report['status'], 'PASS')
        self.assertIsNone(report['actual_cost_usd'])
        self.assertNotIn('test-key', path.read_text())
        self.assertEqual(report['reported_model'], 'test-version')
    def test_exact_boolean_required(self):
        with patch('rcwg_boot.net.request_json', return_value=self.response('{"ok": 1}')):
            report, _ = self.call()
        self.assertEqual(report['status'], 'SCHEMA_MISMATCH')
    def test_dashscope_one_request(self):
        response = {'choices': [{'message': {'content': '{"ok": true}'}}], 'model': 'test-model', 'usage': {'total_tokens': 30}}
        with patch('rcwg_boot.net.request_json', return_value=response) as call:
            report, _ = self.call('dashscope', base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1')
        call.assert_called_once(); self.assertEqual(report['status'], 'PASS')
    def test_failure_not_refunded_or_retried(self):
        with patch('rcwg_boot.net.request_json', side_effect=RuntimeError('HTTP_STATUS_429')) as call:
            report, _ = self.call()
        call.assert_called_once(); self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(report['error_code'], 'HTTP_STATUS_429')
        with sqlite3.connect(self.root/'ledger') as con:
            self.assertEqual(con.execute('SELECT COUNT(*),SUM(micro_usd) FROM reservations').fetchone(), (1,100000))
    def test_malformed_response_recorded(self):
        with patch('rcwg_boot.net.request_json', return_value={'error': 'test-key'}):
            report, path = self.call()
        self.assertEqual(report['status'], 'FAILED'); self.assertNotIn('test-key', path.read_text())
    def test_bad_json_output(self):
        with patch('rcwg_boot.net.request_json', return_value=self.response('not json')):
            report, _ = self.call()
        self.assertEqual(report['status'], 'FAILED')

class Cloud(unittest.TestCase):
    @patch.dict(os.environ, {'RCWG_ARTIFACT_BUCKET': '', 'CLOUD_RUN_EXECUTION': ''})
    def test_missing_config_no_network(self):
        with self.assertRaises(ValueError): cloud.main()
    @patch.dict(os.environ, {'RCWG_ARTIFACT_BUCKET': 'rcwg-test-bucket', 'CLOUD_RUN_EXECUTION': ''})
    def test_local_cloud_entry_blocked(self):
        with self.assertRaises(ValueError): cloud.main()
    @patch.dict(os.environ, {'RCWG_ARTIFACT_BUCKET': 'rcwg-test-bucket', 'CLOUD_RUN_EXECUTION': 'rcwg-boot-smoke-abc'})
    def test_storage_upload_mocked(self):
        report = {'attempt_id': 'boot-abc', 'status': 'PASS', 'api_requests': 0}
        with patch('rcwg_boot.cloud.run', return_value=(report, Path('/unused'))), \
             patch('rcwg_boot.net.request_json', side_effect=[{'access_token': 'fake-token'}, {'generation': '1'}]) as http, \
             patch('builtins.print'):
            cloud.main()
        self.assertEqual(http.call_count, 2)
        self.assertIn('ifGenerationMatch=0', http.call_args_list[1].args[0])
        self.assertIn('Metadata-Flavor', http.call_args_list[0].args[2])

if __name__ == '__main__': unittest.main()
