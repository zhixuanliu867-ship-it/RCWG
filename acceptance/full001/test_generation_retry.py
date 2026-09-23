"""Real offline ServiceClient/index/campaign retry, including COUNT identity."""
import json
from pathlib import Path
import unittest
from rcwg_full.evidence import canonical,write,digest,read
from rcwg_full.services.client import ServiceClient,RequestIndex
from rcwg_full.services.generation import PreparedGenerator
from rcwg_full.campaign.runner import CampaignRunner
from rcwg_full.campaign.store import Conflict
from rcwg_full.data.templates import f1
from rcwg_api.vertex import Response
from test_services import binding,Counter
from support import EvidenceDirectory


class Wire:
    mode='ENGINEERING_REPLAY'
    def __init__(self,items):self.items=list(items);self.calls=[]
    def send(self,kind,body,request_id,*,reservation):
        self.calls.append((kind,request_id));item=self.items.pop(0)
        if isinstance(item,Exception):raise item
        return item


def response(plan):
    return Response(200,canonical({'modelVersion':'fixture-revision','candidates':[{'finishReason':'STOP',
        'content':{'parts':[{'text':canonical(plan).decode()}]}}],
        'usageMetadata':{'promptTokenCount':7,'candidatesTokenCount':9,'totalTokenCount':16}}),{},1)


class GenerationRetry(unittest.TestCase):
    def setUp(self):
        self.tmp=EvidenceDirectory(self.id());self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
        self.case=f1('F1-01',0,'C0')
    def setup_runner(self,responses,*,count=False):
        task=self.case['task'];path=self.root/'task.json';h=write(path,task)
        config=binding();config['count_method']='PROVIDER_COUNT' if count else 'LOCAL_TOKENIZER'
        index=RequestIndex(self.root/'requests');self.addCleanup(index.close)
        self.wire=Wire(responses);self.client=ServiceClient(config,self.wire,None,index)
        generation=PreparedGenerator({task['task_id']:{'task_path':str(path),'task_sha256':h}},
            {'G0':self.client},local_counters={'G0':Counter()})
        base={'task_id':task['task_id'],'family':'F1','condition':'C0','generator':'G0','protocol':'P0','trial_label':17,'ledger_role':'PRIMARY'}
        slots=[{**base,'slot_id':'g','slot_kind':'generation','expected_dependencies':[]},
            {**base,'slot_id':'e','slot_kind':'execution','generation_slot_id':'g','expected_dependencies':['g']}]
        runner=CampaignRunner(self.root/'campaign',slots,manifest_hash='a'*64,spec_hash='b'*64,mode='ENGINEERING_REPLAY',
            generate=generation,execute=lambda *a:{'status':'COMPLETED','fixture_only':True})
        self.addCleanup(runner.close);return runner
    def test_resolved_http_facility_retry_retains_count_and_parent_then_runs_dependent(self):
        count=Response(200,canonical({'totalTokens':23}),{},1)
        runner=self.setup_runner([count,Response(503,b'{}',{},1),count,response(self.case['plan'])],count=True)
        self.assertEqual(runner.run()['paused'][0]['reason'],'INFRA_FAILURE')
        retried=runner.retry_failed_generation('g');self.assertEqual(retried['actual_attempts_this_invocation'][0]['status'],'COMPLETED')
        self.assertEqual(runner.run()['status'],'TERMINAL')
        observations=[r for r in runner.store.observations('ENGINEERING_REPLAY') if r['slot_kind']=='generation']
        self.assertEqual([r['ledger_role'] for r in observations],['PRIMARY','INFRA_RETRY'])
        self.assertEqual(observations[1]['parent_attempt_id'],observations[0]['attempt_id'])
        self.assertEqual(len(observations[1]['reconciliation_evidence']['requests']),2)
        self.assertEqual([k for k,r in self.wire.calls],['COUNT','G','COUNT','G'])
        self.assertEqual(len({r for k,r in self.wire.calls}),4)
    def test_second_facility_retry_is_rejected(self):
        runner=self.setup_runner([Response(503,b'{}',{},1),Response(503,b'{}',{},1)])
        runner.run();runner.retry_failed_generation('g')
        with self.assertRaisesRegex(Conflict,'RETRY_LIMIT'):runner.retry_failed_generation('g')
        self.assertEqual(len(self.wire.calls),2)
    def test_unknown_send_and_model_text_are_never_retried(self):
        runner=self.setup_runner([TimeoutError('unknown remote send')]);runner.run()
        with self.assertRaisesRegex(Conflict,'NOT_ALLOWED'):runner.retry_failed_generation('g')
        self.assertEqual(len(self.wire.calls),1)
    def test_changed_binding_or_raw_response_blocks_retry(self):
        runner=self.setup_runner([Response(503,b'{}',{},1)]);runner.run()
        old=self.client.binding['reported_revision'];self.client.binding['reported_revision']='changed'
        with self.assertRaisesRegex(Conflict,'CONTEXT_CHANGED'):runner.retry_failed_generation('g')
        self.client.binding['reported_revision']=old
        (self.client.index.root/self.wire.calls[0][1]/'response.raw').write_bytes(b'changed')
        with self.assertRaisesRegex(Conflict,'RESPONSE_CHANGED'):runner.retry_failed_generation('g')
        self.assertEqual(len(self.wire.calls),1)
