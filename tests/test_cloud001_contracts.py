from copy import deepcopy
import unittest
from rcwg_cloud.contracts import manifest,authorization,PLAN_SHA,OLD_P0_RESULT
from rcwg_cloud.transport import CloudError,PROJECT,BUCKET,RUNTIME,MODEL
from rcwg_cloud.prompts import PROFILE

def ref(name):return {'object':'cloud001/'+name,'generation':'1','sha256':'a'*64}
def fixture():
    m={'version':'CLOUD001_EXPECTED_MANIFEST_1','phase':'live','project_id':PROJECT,'region':'us-central1','bucket':BUCKET,'runtime_identity':RUNTIME,
       'model':MODEL,'model_location':'global','prompt_profile':PROFILE,'image_digest':'sha256:'+'a'*64,'image_source_sha256':'b'*64,
       'approval':ref('approvals/owner.json'),'created_unix_s':1000,'expires_unix_s':2000,'inputs':{k:ref('inputs/'+k) for k in ('task','records','recipe')},
       'expected_generation_slots':['p0','p1'],'max_generate':3,'max_count':3,'auto_retries':0,'budget_microusd':1000000,'formal_ready':False,
       'pricing':ref('approvals/pricing.json'),'c1_review':ref('approvals/c1.json'),'change_plan_sha256':PLAN_SHA}
    a={'version':'CLOUD001_OWNER_APPROVAL_1','approved':True,'project_id':PROJECT,'owner':'zhixuanliu867@gmail.com','change_plan_sha256':PLAN_SHA,
       'region':'us-central1','working_budget_microusd':5000000,'model_budget_microusd':1000000,'new_batches':1,'generate_max':3,'count_max':3,'auto_retries':0,
       'approved_unix_s':900,'expires_unix_s':2000,'user_message_sha256':'c'*64}
    p={'version':'CLOUD001_OFFICIAL_PRICE_RECHECK_1','model':MODEL,'location':'global','available':True,'input_usd_per_million':'0.25','output_usd_per_million':'1.50',
       'observed_unix_s':1000,'sources':['https://cloud.google.com/vertex-ai/generative-ai/pricing','https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-1-flash-lite']}
    c={'version':'CLOUD001_INDEPENDENT_C1_REVIEW_1','status':'C1_CLOUD_REPLAY_ACCEPTED','image_digest':m['image_digest'],'image_source_sha256':m['image_source_sha256'],
       'replay_manifest_sha256':'d'*64,'replay_archive_sha256':'e'*64,'platform_execution':'rcwg-cloud001-replay-12345','p0_result_sha256':OLD_P0_RESULT,
       'p1_static_code':'REFERENCE_SYNTAX','model_dispatches':0,'reviewed_unix_s':1000,'formal_ready':False}
    return m,a,p,c

class CloudContractTests(unittest.TestCase):
    def test_valid_closed_synthetic_manifest_and_approval(self):
        m,a,p,c=fixture();self.assertEqual(manifest(m,'live',now=1001),m)
        self.assertEqual(authorization(m,a,p,c,now=1001)['status'],'OWNER_AUTHORIZATION_AND_PRECONDITIONS_VALIDATED')
    def test_false_or_partial_or_old_approval_cannot_authorize_live(self):
        for changed in ({'approved':False},{'region':'global'},{'change_plan_sha256':'f'*64},{'new_batches':2},{'model_budget_microusd':5000000}):
            m,a,p,c=fixture();a.update(changed)
            with self.assertRaises(CloudError):authorization(m,a,p,c,now=1001)
    def test_unknown_fields_or_bool_for_numeric_limits_rejected(self):
        m,*_=fixture();m['max_count']=True
        with self.assertRaises(CloudError):manifest(m,'live',now=1001)
        m,*_=fixture();m['allow_repair']=True
        with self.assertRaises(CloudError):manifest(m,'live',now=1001)
    def test_manifest_must_be_frozen_before_dispatch_and_unexpired(self):
        m,*_=fixture()
        for now in (999,2000,2001):
            with self.assertRaises(CloudError):manifest(m,'live',now=now)
    def test_cross_project_bucket_principal_and_endpoint_blocked(self):
        for k in ('project_id','bucket','runtime_identity','model_location','model','region'):
            m,*_=fixture();m[k]='different'
            with self.assertRaises(CloudError):manifest(m,'live',now=1001)
    def test_input_cannot_pin_runtime_writable_output_as_approval(self):
        m,*_=fixture();m['approval']=ref('output/forged.json')
        with self.assertRaises(CloudError):manifest(m,'live',now=1001)
    def test_no_c1_or_different_image_cannot_authorize_live(self):
        m,a,p,c=fixture()
        for value in (None,dict(c,status='RUNTIME_SELF_REPORT'),dict(c,image_digest='sha256:'+'f'*64),dict(c,formal_ready=True)):
            with self.assertRaises(CloudError):authorization(m,a,p,value,now=1001)
    def test_price_over_24h_or_changed_model_requires_stop(self):
        m,a,p,c=fixture()
        for update in ({'observed_unix_s':-86400},{'model':'another-model'},{'input_usd_per_million':'0.30'},{'available':False}):
            changed=dict(p,**update)
            with self.assertRaises(CloudError):authorization(m,a,changed,c,now=1001)
    def test_input_generation_and_real_image_digest_required(self):
        m,*_=fixture();m['image_digest']='latest'
        with self.assertRaises(CloudError):manifest(m,'live',now=1001)
        m,*_=fixture();m['inputs']['records']['generation']='latest'
        with self.assertRaises(CloudError):manifest(m,'live',now=1001)
    def test_generation_denominator_cannot_shrink(self):
        m,*_=fixture();m['expected_generation_slots']=['p0']
        with self.assertRaises(CloudError):manifest(m,'live',now=1001)

if __name__=='__main__':unittest.main()
