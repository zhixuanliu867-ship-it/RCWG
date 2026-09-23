"""A separately supervised worker consumes exact replay bytes and public sources."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from rcwg_full.data.prepare import prepare
from rcwg_full.evidence import digest,write,read
from rcwg_full.runtime.documents import canonical_document,compose,piece
from rcwg_full.runtime.supervisor import execute,context_for
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.compiler import FullCompiler
from rcwg_full.verification.semantic import verify_semantics
from support import EvidenceDirectory


class DocumentWorker(unittest.TestCase):
    def setUp(self):
        self.evidence=EvidenceDirectory(self.id());self.root=Path(self.evidence.name)
        self.doc=canonical_document('paper1','v1','Title',[{'heading':'结果','text':'对象甲的剂量为 5 mg。🙂'}])
        self.fields={'query_id':'Utf8','dose':'Int64'}
        self.task={'task_id':'full001-document-worker','instruction':'对 paper1 的问题 q1 返回 dose=以mg为单位的剂量，保留证据。','resources':{'cpu_slots':2,'worker_memory_limit_bytes':64*1024**2,'wall_timeout_s':20},'tool_catalog_id':'full001-compat1',
          'datasets':[{'id':'dataset:docs','kind':'document_index','domain':'papers','revision':'v1','schema_source':'generated','schema':{'document_id':'Utf8','revision':'Utf8','canonical_text':'Utf8'},'id_type':'Utf8','id_field':'document_id','stats':{'document_count':1},'indexes':[]},
                      {'id':'dataset:ids','kind':'id_selection','domain':'papers','revision':'v1','schema_source':'generated','id_type':'Utf8','ranked':False,'stats':{'item_count':1}}],
          'output_contract':{'id':'result','type':'evidence','mode':'evidence_supported','domain':'papers','revision':'v1','fields':list(self.fields),'schema':self.fields}}
        self.plan={'ir_version':'1.0','task_id':self.task['task_id'],'external_inputs':{'docs':'dataset:docs','ids':'dataset:ids'},'nodes':[
          {'id':'read','operator':'read_documents','implementation':'batched','inputs':{'index':'$input.docs','ids':'$input.ids'},'params':{'fields':['canonical_text'],'batch_size':1},'outputs':{'documents':'DocumentStream'}},
          {'id':'extract','operator':'semantic_extract','implementation':'fixed_e0','inputs':{'documents':'read.documents'},'params':{'question':'q1: 对象甲的剂量 mg','field_schema':self.fields,'context_budget':1000},'outputs':{'evidence':'EvidenceTable'}},
          {'id':'check','operator':'evidence_validate','implementation':'span_check','inputs':{'index':'$input.docs','evidence':'extract.evidence'},'params':{'strict':True},'outputs':{'evidence':'EvidenceTable'}},
          {'id':'emit','operator':'emit','implementation':'json_artifact','inputs':{'rows':'check.evidence'},'params':{'output_contract':'result'},'outputs':{'result':'Result'}}],'result':'emit.result'}
        self.task,_,self.manifest=prepare(self.task,{'dataset:docs':[self.doc],'dataset:ids':['paper1']},self.root/'data')
        at=self.doc['canonical_text'].index('5 mg');citation={'document_id':'paper1','revision':'v1','start_cp':at,'end_cp':at+4,'quote':'5 mg'}
        self.reply=[{'query_id':'q1','dose':5,'evidence':[citation]}]
        request={'service_id':'engineering-replay-e0','question':self.plan['nodes'][1]['params']['question'],'field_schema':self.fields,'contexts':[compose([piece(self.doc,0,len(self.doc['canonical_text']))])]}
        self.replay=self.root/'replay.json';write(self.replay,{'revision':'full001-engineering-replay-1','service_id':'engineering-replay-e0','responses':{digest(request):self.reply}})
        self.private={'fields':{'query_id':{'acceptable_values':['q1'],'critical':True},'dose':{'acceptable_values':[5],'critical':True}},'evidence_obligations':[{'id':'dose-support','acceptable_witness_sets':[[citation]]}],'exact_fields':True}
    def tearDown(self):self.evidence.cleanup()
    def test_supervised_document_replay_has_sealed_sources_and_independent_verification(self):
        def verify(actual,out):return verify_semantics({'fields':{k:actual[0][k] for k in self.fields},'evidence':actual[0]['evidence']},self.private)
        report=execute(self.task,self.plan,self.manifest,build=os.environ['RCWG_FULL_BUILD'],output=self.root/'run',mode='ENGINEERING_REPLAY',semantic_replay=self.replay,verify=verify)
        self.assertEqual(report['terminal_status'],'COMPLETED',report);self.assertEqual(report['verification']['status'],'PASS')
        self.assertEqual(report['paid_calls'],0);self.assertFalse(report['formal_ready']);self.assertEqual(report['process_group_final']['live'],[])
        request=json.loads(read(self.root/'run/request.json'));self.assertNotIn('private',str(request));self.assertIn('semantic_replay',request)
    def test_missing_request_never_falls_back_to_live_service(self):
        plan=deepcopy(self.plan);plan['nodes'][1]['params']['question']='q2 changed'
        report=execute(self.task,plan,self.manifest,build=os.environ['RCWG_FULL_BUILD'],output=self.root/'changed',mode='ENGINEERING_REPLAY',semantic_replay=self.replay)
        self.assertEqual(report['terminal_status'],'INFRA_FAILURE',report);self.assertEqual(report['failure']['code'],'REPLAY_REQUEST_MISSING');self.assertEqual(report['paid_calls'],0)
    def test_replay_requires_explicit_mode(self):
        with self.assertRaisesRegex(ValueError,'REPLAY_MODE_FORBIDDEN'):execute(self.task,self.plan,self.manifest,build=os.environ['RCWG_FULL_BUILD'],output=self.root/'wrong-mode',semantic_replay=self.replay)
    def test_bound_context_reuses_original_immutable_context_type(self):
        from rcwg_spec.binding import RunnerContext
        catalog=DataCatalog(self.manifest).bind(self.task)
        context=context_for(self.task,catalog,os.environ['RCWG_FULL_BUILD'],mode='ENGINEERING_REPLAY',replay_sha256='a'*64)
        changed=context_for(self.task,catalog,os.environ['RCWG_FULL_BUILD'],mode='ENGINEERING_REPLAY',replay_sha256='b'*64)
        self.assertIs(type(context),RunnerContext);self.assertNotEqual(context.as_dict()['identity'],changed.as_dict()['identity'])
