from copy import deepcopy
from pathlib import Path
import hashlib,io,json,tempfile,unittest,zipfile
from rcwg_cloud.review import review,unpack_checked,missing_archive_reconciliation
from rcwg_cloud.transport import CloudError
from rcwg_cloud.runtime import run_batch
from rcwg_spec.common import canonical,digest
from rcwg_exec.demo import prepare_fixture
from rcwg_api.mock import wire_fixtures
from test_cloud001_runtime import ObjectServer,SyntheticVertex

class CloudReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.task,self.plans,self.recipe,data=prepare_fixture(self.root/'fixture');self.s=ObjectServer()
        self.m={'phase':'live','inputs':{k:self.s.put_owner('cloud001/inputs/'+k,raw) for k,raw in [('task',canonical(self.task)),('records',data.read_bytes()),('recipe',canonical(self.recipe))]}}
    def make_archive(self,plan=None):
        v=SyntheticVertex(wire_fixtures(plan or self.plans['streaming_heap']),self.s)
        run_batch(self.m,store=self.s,vertex=v,root=self.root/'runtime',execution_id='rcwg-cloud001-live-12345',context={'mode':'OFFLINE_SYNTHETIC_NO_CLOUD'})
        return self.s.objects['cloud001/output/live/archive.zip'],json.loads(self.s.objects['cloud001/output/live/complete.json'])
    def test_independent_raw_wire_and_f1_reread_does_not_imply_cloud_acceptance(self):
        raw,marker=self.make_archive();r=review(raw,marker,self.m,self.root/'reread')
        self.assertEqual(len(r['transport_observations']),6);self.assertEqual(r['slots']['p0']['answer'],'PASS');self.assertEqual(r['slots']['p1']['answer'],'PASS')
        self.assertEqual(r['physical_parity']['status'],'FINAL_PROVIDER_PHYSICAL_PARITY_PASS');self.assertFalse(r['cloud_engineering_accepted'])
    def test_wrong_answer_independently_remains_fail(self):
        raw,marker=self.make_archive(self.plans['omitted_filter']);r=review(raw,marker,self.m,self.root/'reread')
        self.assertEqual(r['slots']['p0']['answer'],'FAIL');self.assertEqual(r['slots']['p1']['answer'],'FAIL')
    def test_download_hash_change_fails_before_extraction(self):
        raw,marker=self.make_archive()
        with self.assertRaises(CloudError):review(raw+b'corrupt',marker,self.m,self.root/'reread')
        self.assertFalse((self.root/'reread').exists())
    def test_changed_expected_manifest_is_rejected(self):
        raw,marker=self.make_archive();m=deepcopy(self.m);m['extra']='changed'
        with self.assertRaises(CloudError):review(raw,marker,m,self.root/'reread')
    def test_archive_traversal_is_rejected_even_with_fresh_outer_hash(self):
        raw,marker=self.make_archive();b=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as src,zipfile.ZipFile(b,'w') as dst:
            for i in src.infolist():dst.writestr(i,src.read(i.filename))
            dst.writestr('../escape',b'x')
        bad=b.getvalue();marker['archive']['sha256']=hashlib.sha256(bad).hexdigest()
        with self.assertRaises(CloudError):review(bad,marker,self.m,self.root/'reread')
        self.assertFalse((self.root/'escape').exists())
    def test_oom_or_missing_flush_retains_two_unknown_slots_no_retry(self):
        r=missing_archive_reconciliation(self.m,{'state':'FAILED','reason':'OOM_KILLED'})
        self.assertEqual(r['generation_denominator'],2);self.assertEqual(set(r['slots']),{'p0','p1'})
        self.assertFalse(r['retry_authorized']);self.assertEqual(r['status'],'INCOMPLETE_EVIDENCE')

if __name__=='__main__':unittest.main()
