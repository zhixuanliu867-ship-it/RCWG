from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from test_analysis import sample
from rcwg_full.analysis.rebuild import rebuild
from rcwg_full.campaign.sealing import seal_package,unseal,verify_seal,relative_file
from rcwg_full.campaign.store import CampaignStore
from rcwg_full.evidence import read,sha


def receipt(subject):
    now=datetime.now(timezone.utc)
    return {'receipt_id':'test-audit','actor_id':'fixture-auditor','actor_role':'Auditor',
            'approved':True,'action':'AUDIT_UNSEAL','subject_hash':subject,
            'valid_from':(now-timedelta(hours=1)).isoformat(),'valid_until':(now+timedelta(hours=1)).isoformat()}


class SealedAnalysisTests(unittest.TestCase):
    def test_rebuild_reproducible_numbers_and_does_not_modify_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); package=root/'package';package.mkdir()
            expected,observed=sample()
            manifest=seal_package(package,expected_slots=expected,observations=observed,mode='ENGINEERING_NATIVE',source_identity='fixture-source')
            path=package/'sealed-manifest.json'
            with self.assertRaises(OSError):rebuild(path,root/'denied')
            unseal(path,receipt(manifest['manifest_hash']))
            before={p.name:sha(read(p)) for p in package.iterdir()}
            left=rebuild(path,root/'a');right=rebuild(path,root/'b')
            self.assertEqual(left['numerical_tables_hash'],right['numerical_tables_hash'])
            self.assertEqual(left['outputs'],right['outputs'])
            self.assertEqual(before,{p.name:sha(read(p)) for p in package.iterdir()})
            result=json.loads((root/'a/success_budget.json').read_text('utf8'))
            self.assertEqual(result['rows'][0]['point'],1)
            self.assertTrue((root/'a/report.html').is_file())

    def test_absent_duplicate_and_active_attempts_cannot_seal(self):
        e,o=sample()
        with tempfile.TemporaryDirectory() as tmp:
            for index,rows in enumerate([o[:-1],o+[o[0]],[dict(row,status='RUNNING') for row in o]]):
                path=Path(tmp)/str(index);path.mkdir()
                with self.assertRaises(ValueError):seal_package(path,expected_slots=e,observations=rows,mode='ENGINEERING_NATIVE',source_identity='s')

    def test_changed_artifact_and_wrong_auditor_receipt_rejected(self):
        e,o=sample()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);m=seal_package(path,expected_slots=e,observations=o,mode='ENGINEERING_NATIVE',source_identity='s')
            with self.assertRaisesRegex(PermissionError,'RECEIPT'):
                unseal(path/'sealed-manifest.json',dict(receipt(m['manifest_hash']),actor_role='Operator'))
            with self.assertRaisesRegex(PermissionError,'RECEIPT'):
                unseal(path/'sealed-manifest.json',receipt('wrong-hash'))
            (path/'observations.json').write_text('[]',encoding='utf8')
            with self.assertRaisesRegex(ValueError,'CHANGED'):verify_seal(path/'sealed-manifest.json')

    def test_paths_cannot_escape_and_reconcile_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ['../escape','C:/x','a\\b','/absolute']:
                with self.assertRaisesRegex(ValueError,'PATH'):relative_file(tmp,name)
            dbpath=Path(tmp)/'campaign.db';store=CampaignStore(dbpath);store.register([{'slot_id':'s'}]);store.close()
            before=sha(read(dbpath));store=CampaignStore(dbpath,read_only=True)
            try:
                self.assertEqual(store.reconcile()[0]['status'],'NOT_RUN')
                with self.assertRaisesRegex(PermissionError,'READ_ONLY'):store.claim('s','w','key')
            finally:store.close()
            self.assertEqual(before,sha(read(dbpath)))

    def test_builder_separates_private_files(self):
        from rcwg_full.data.templates import build
        with tempfile.TemporaryDirectory() as tmp:
            bundle=build('F1-01',0,'C0',Path(tmp)/'public')
            self.assertFalse((bundle['manifest_path'].parent/'private_verifier_recipe.json').exists())
            self.assertTrue((bundle['private_directory']/'private_verifier_recipe.json').exists())
