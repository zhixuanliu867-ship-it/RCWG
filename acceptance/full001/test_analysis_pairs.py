from copy import deepcopy
from pathlib import Path
import json
import unittest
from rcwg_full.analysis.metrics import common_reference_domain,normalize
from rcwg_full.analysis.rebuild import rebuild
from rcwg_full.campaign.sealing import seal_package,unseal
from rcwg_full.evidence import digest,write,read
from test_analysis import sample
from test_sealed_analysis import receipt
from support import EvidenceDirectory


class AnalysisPairsTests(unittest.TestCase):
    def setUp(self):self.evidence=EvidenceDirectory('pairs-'+digest(self.id())[:16]);self.root=Path(self.evidence.name)
    def tearDown(self):self.evidence.cleanup()
    def test_missing_method_log_does_not_reduce_frozen_reference_domain(self):
        e,o=sample();p=deepcopy(e);v=deepcopy(o)
        for r in p:r.update(protocol='P1',slot_id=r['slot_id']+'p1')
        for r in v:r.update(protocol='P1',slot_id=r['slot_id']+'p1',attempt_id=r['attempt_id']+'p1')
        refs={r['task_id']:{'confirmed':True,'elapsed_ns':100,'context_hash':'ctx'} for r in e}
        domain=common_reference_domain(e+p,refs)
        n=normalize(e+p,o+v[:-1],refs)
        self.assertEqual(domain,{r['task_id'] for r in e});self.assertEqual(sum(r['task_id'] in domain for r in n['rows']),48)
        self.assertEqual(sum(r['selected_attempt'] is None for r in n['rows']),1)
        with self.assertRaisesRegex(ValueError,'FROZEN_REFERENCE_CONTEXT'):common_reference_domain(e+p,refs,mode='FORMAL')

    def test_e2_rebuild_computes_paired_effect_and_holm_family(self):
        e,o=sample();e=[r for r in e if r['condition']=='C1'];o=[r for r in o if r['condition']=='C1']
        diagnostic=[];observed=[]
        for r in e:
            diagnostic.append({**r,'slot_id':'f-'+r['slot_id'],'ledger_role':'DIAGNOSTIC','experiment_id':'E2','arm':'Frozen'})
        for r in o:
            observed.append({**r,'slot_id':'f-'+r['slot_id'],'attempt_id':'f-'+r['attempt_id'],'ledger_role':'DIAGNOSTIC','experiment_id':'E2','arm':'Frozen',
                             'plan_hash':'c0-plan','c0_source_plan_hash':'c0-plan','semantic':False})
        package=self.root/'sealed';package.mkdir()
        m=seal_package(package,expected_slots=e+diagnostic,observations=o+observed,mode='ENGINEERING_NATIVE',source_identity='fixture')
        unseal(package/'sealed-manifest.json',receipt(m['manifest_hash']));rebuild(package/'sealed-manifest.json',self.root/'analysis')
        rows=json.loads(read(self.root/'analysis/hypotheses.json'))['rows'];self.assertEqual(len(rows),18)
        result=next(r for r in rows if r['id']=='G0.AdaptiveFrozen')
        self.assertEqual(result['effect'],1);self.assertEqual(result['status'],'ESTIMATED');self.assertEqual(result['p_holm'],1)
        self.assertEqual(len(json.loads(read(self.root/'analysis/frozen_adaptive.json'))['rows']),12)

    def test_recomputed_audit_release_hash_does_not_hide_wrong_receipt(self):
        e,o=sample();package=self.root/'sealed';package.mkdir()
        m=seal_package(package,expected_slots=e,observations=o,mode='ENGINEERING_NATIVE',source_identity='fixture')
        release=unseal(package/'sealed-manifest.json',receipt(m['manifest_hash']));release['receipt']['subject_hash']='d'*64
        release['release_hash']=digest({k:v for k,v in release.items() if k!='release_hash'})
        (package/'audit-release.json').write_text(json.dumps(release),encoding='utf8')
        with self.assertRaisesRegex(PermissionError,'RECEIPT_BINDING'):rebuild(package/'sealed-manifest.json',self.root/'denied')
