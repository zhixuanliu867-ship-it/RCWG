from pathlib import Path
import unittest
from rcwg_full.reference.external import registry,prepare,import_observation
from rcwg_full.evidence import digest,write
from rcwg_full.data.templates import f1
from support import EvidenceDirectory


class ExternalInterchangeTests(unittest.TestCase):
    def setUp(self):self.evidence=EvidenceDirectory('external-'+digest(self.id())[:16]);self.root=Path(self.evidence.name)
    def tearDown(self):self.evidence.cleanup()
    def test_all_upstream_tracks_remain_explicitly_unexecuted(self):
        rows=registry()['tracks'];self.assertEqual({r['id'] for r in rows},{'TPS-Bench','WorFEval','SemBench','LOTUS','DocETL'})
        self.assertTrue(all(r['actual_original_runs']==0 and r['upstream_revision'] is None for r in rows))
        self.assertEqual(next(r for r in rows if r['id']=='TPS-Bench')['upstream_url'],'https://github.com/hanwenxu1/mcp-agent')
    def test_public_interchange_keeps_protocol_changes_and_missing_dependencies(self):
        task=f1('F1-01',0,'C0')['task'];adaptation={'mapping_revision':'fixture-1','preserved_semantics':['task output'],
            'changed_semantics':['RCWG fixture replaces upstream dataset'],'unsupported_obligations':['no original run']}
        result=prepare('WorFEval',task,adaptation=adaptation,output=self.root/'package')
        self.assertFalse(result['execution_authorized']);self.assertEqual(result['ledger_role'],'EXTERNAL_REPLICATION')
        self.assertIn('UPSTREAM_SNAPSHOT_NOT_PINNED',result['blockers']);self.assertFalse(result['original_reproduction_claim'])
        task['private_gold']='forbidden'
        with self.assertRaises(ValueError):prepare('WorFEval',task,adaptation=adaptation,output=self.root/'forbidden')
    def test_import_is_hash_bound_and_never_promoted_to_primary_or_original_reproduction(self):
        adaptation={'mapping_revision':'fixture-1','preserved_semantics':[],'changed_semantics':['fixture'],'unsupported_obligations':[]}
        package=prepare('LOTUS',f1('F1-01',0,'C0')['task'],adaptation=adaptation,output=self.root/'package')
        h=write(self.root/'fixture-output.json',{'fixture':True})
        row={'track_id':'LOTUS','package_hash':package['manifest_hash'],'attempt_id':'fixture-only','mode':'ENGINEERING_REPLAY',
            'upstream_revision':None,'command':['fixture-producer'],'exit_code':0,'artifacts':{'fixture-output.json':h},'metrics':{'latency_ns':None}}
        imported=import_observation(self.root/'package/manifest.json',row,artifact_root=self.root,output=self.root/'imported.json')
        self.assertEqual(imported['status'],'IMPORTED_UNVERIFIED');self.assertFalse(imported['primary_ledger_eligible'])
        with self.assertRaisesRegex(ValueError,'REVISION_UNBOUND'):
            import_observation(self.root/'package/manifest.json',{**row,'mode':'UPSTREAM_EXECUTION'},artifact_root=self.root,output=self.root/'false.json')
        (self.root/'fixture-output.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_CHANGED'):
            import_observation(self.root/'package/manifest.json',row,artifact_root=self.root,output=self.root/'tamper.json')
