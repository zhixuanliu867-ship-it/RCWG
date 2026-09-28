from pathlib import Path
import sys
import unittest
from rcwg_full.acceptance_stages import run_stage
from support import EvidenceDirectory


class AcceptanceRecovery(unittest.TestCase):
    def setUp(self):self.evidence=EvidenceDirectory(self.id());self.root=Path(self.evidence.name)
    def tearDown(self):self.evidence.cleanup()
    def stage(self,name,code,**kwargs):
        return run_stage(self.root,name,[sys.executable,'-I','-c',code],source_hash='test-source',cwd=self.root,**kwargs)
    def test_real_process_completion_and_readonly_resume(self):
        code='print("actual child")';first=self.stage('ok',code);self.assertEqual(first['status'],'PASS')
        self.assertEqual(first,self.stage('ok',code,resume=True))
        self.assertIn(b'actual child',(self.root/'ok/stdout.log').read_bytes())
    def test_failed_exit_is_preserved_and_independent_stage_runs(self):
        result=self.stage('failure','raise SystemExit(1)');self.assertEqual(result['status'],'FAIL')
        self.assertEqual(result,self.stage('failure','raise SystemExit(1)',resume=True))
        self.assertEqual(self.stage('independent','print(42)')['status'],'PASS')
    def test_partial_stage_is_reported_blocked_without_launch_or_overwrite(self):
        stage=self.root/'partial';stage.mkdir();(stage/'stdout.log').write_bytes(b'old partial output')
        result=self.stage('partial','raise RuntimeError("must not launch")',resume=True)
        self.assertEqual(result['exit_code'],2);self.assertEqual(result['blocker'],'INCOMPLETE_STAGE_REQUIRES_RECONCILIATION')
        self.assertFalse(result['launch_performed']);self.assertEqual((stage/'stdout.log').read_bytes(),b'old partial output')
    def test_tampered_or_added_stage_artifacts_prevent_reuse(self):
        self.stage('proof','print(3)');(self.root/'proof/unrecorded.txt').write_text('added',encoding='utf8')
        result=self.stage('proof','print(3)',resume=True)
        self.assertEqual(result['blocker'],'STAGE_RESUME_ARTIFACT');self.assertFalse(result['launch_performed'])
