"""Previously uncovered implementations execute through the real worker.

Each successful branch is tied to an independent expected result and a sealed
node_finished event. Engineering service/model fixtures are labeled explicitly.
"""
import copy,json,os,unittest
from pathlib import Path
from rcwg_full.data.templates import build,Plan,task_shell
from rcwg_full.data.prepare import prepare
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.runtime.supervisor import execute
from rcwg_full.runtime.events import verify_journal
from rcwg_full.evidence import read,write
from rcwg_full.verification.compare import check_output
from support import EvidenceDirectory


class DispatchCompletion(unittest.TestCase):
    def setUp(self):
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)

    def run_bound(self,task,plan,path,expected,branch,*,name='run',stage='primary_execution',replay=None,verifier=None):
        out=self.root/name
        def verify(actual,directory):
            if verifier:return verifier(actual,directory)
            return {'status':'PASS' if actual==expected else 'FAIL','expected':expected,'actual':actual}
        result=execute(task,plan,path,build=os.environ['RCWG_FULL_BUILD'],output=out,stage=stage,
            mode='ENGINEERING_REPLAY' if replay else 'ENGINEERING_NATIVE',semantic_replay=replay,verify=verify)
        self.assertEqual(result['terminal_status'],'COMPLETED',result)
        self.assertEqual(result['verification']['status'],'PASS',result['verification'])
        events=verify_journal(out/'worker/events.jsonl')
        finished={e['payload']['operator']+':'+e['payload']['implementation'] for e in events if e['event_kind']=='node_finished'}
        self.assertIn(branch,finished);self.assertFalse(result['formal_ready']);self.assertEqual(result['paid_calls'],0)
        write(out/'dispatch-proof.json',{'branch':branch,'verification':'PASS','journal':'worker/events.jsonl'})
        return json.loads(read(out/'worker/result.json')),events

    def variant(self,template,operator,implementation):
        built=build(template,0,'C0',self.root/'data');plan=copy.deepcopy(built['plan'])
        node=next(n for n in plan['nodes'] if n['operator']==operator);node['implementation']=implementation
        def verifier(actual,out):
            if template.startswith('F5-'):
                from rcwg_full.verification.document_oracle import verify_document_result
                return verify_document_result(actual,built['recipe']['expected'],built['rows']['documents'],events=verify_journal(out/'worker/events.jsonl'))
            return check_output(actual,built['recipe']['expected'],built['recipe'])
        self.run_bound(built['task'],plan,built['manifest_path'],None,operator+':'+implementation,
                       replay=built['semantic_replay_path'],verifier=verifier)

    def test_graph_filter_index_filter(self):self.variant('F3-04','graph_filter','index_filter')
    def test_graph_neighbors_indexed_adjacency(self):self.variant('F3-10','graph_neighbors','indexed_adjacency')
    def test_graph_reachability_dfs(self):self.variant('F3-01','graph_reachability','dfs')
    def test_join_block_nested(self):self.variant('F2-01','join','block_nested')
    def test_set_op_sorted_merge(self):self.variant('F1-08','set_op','sorted_merge')
    def test_evidence_merge_by_document(self):self.variant('F5-07','evidence_merge','by_document')

    def test_scan_index_range(self):
        built=build('F1-01',0,'C0',self.root/'original');task=copy.deepcopy(built['task']);plan=copy.deepcopy(built['plan'])
        public=task['datasets'][0];public['indexes']=[{'id':'score-range','kind':'range','fields':['score'],'revision':public['revision'],'source':'prepared-range'}]
        catalog=DataCatalog(built['manifest_path']);values={s:src.value() for s,src in catalog.sources.items()}
        task,_,path=prepare(task,values,self.root/'indexed')
        next(n for n in plan['nodes'] if n['operator']=='scan')['implementation']='index_range'
        self.run_bound(task,plan,path,built['recipe']['expected'],'scan:index_range')

    def test_branch_predicate_branch_then_and_else(self):
        built=build('F1-01',0,'C0',self.root/'original')
        for flag in [True,False,None]:
            task=copy.deepcopy(built['task']);plan=copy.deepcopy(built['plan']);name=str(flag)
            task['datasets'].append({'id':'dataset:flag','kind':'scalar','revision':'v1','schema_source':'public-fixture','type':{'kind':'Nullable','item':'Bool'} if flag is None else 'Bool','value':flag})
            catalog=DataCatalog(built['manifest_path']);values={s:src.value() for s,src in catalog.sources.items()};values['dataset:flag']=flag
            task,_,path=prepare(task,values,self.root/('data-'+name));plan['external_inputs']['flag']='dataset:flag'
            emit=next(n for n in plan['nodes'] if n['operator']=='emit');source=emit['inputs']['rows'];plan['nodes'].remove(emit)
            arm={'bindings':{'x':source},'nodes':[],'yield':{'rows':'$bound.x'}}
            other=copy.deepcopy(arm);other['nodes']=[{'id':'none','operator':'filter','implementation':'vectorized',
                'inputs':{'rows':'$bound.x'},'params':{'predicate':{'literal':False}},'outputs':{'rows':'Table'}}];other['yield']['rows']='none.rows'
            plan['nodes'].append({'id':'choose','operator':'branch','implementation':'predicate_branch','inputs':{'condition':'$input.flag'},
                'params':{'predicate':{'field':'condition'}},'outputs':{'rows':'Table'},'regions':{'then':arm,'else':other}});plan['result']='choose.rows'
            if flag is None:
                report=execute(task,plan,path,build=os.environ['RCWG_FULL_BUILD'],output=self.root/name)
                self.assertEqual(report['terminal_status'],'MODEL_FAILURE',report)
                self.assertEqual(report['failure']['code'],'BRANCH_PREDICATE_UNKNOWN');continue
            _,events=self.run_bound(task,plan,path,built['recipe']['expected'] if flag else [],'branch:predicate_branch',name=name)
            self.assertEqual([e['payload']['selected'] for e in events if e['event_kind']=='region_selection'],['then' if flag else 'else'])

    def stats(self,impl):
        import pyarrow as pa
        from rcwg_full.compiler import FullCompiler
        from rcwg_full.data.templates import descriptor
        rows=[{'id':i,'score':float(i)} for i in range(37)];task=task_shell('F1-01',0,'C0','Generation probe',{'id':'result','type':'records','mode':'exact','fields':['id'],'schema':{'id':'Int64'}})
        task['information_level']='I2';task['datasets']=[descriptor('records',{'id':'Int64','score':'Float64'},rows)]
        task,_,path=prepare(task,{'dataset:records':pa.Table.from_pylist(rows)},self.root/'data')
        plan=Plan(task['task_id']);plan.value['external_inputs']['source']='dataset:records'
        params={'fields':['id']};params.update({'sample_size':5} if impl=='sample' else {})
        result=plan.add('probe','stats',impl,{'source':'$input.source'},params,{'stats':'Stats'});plan.value['result']=result
        denied=FullCompiler().compile(task,plan.value);self.assertEqual(denied['status'],'PLAN_INVALID')
        self.assertIn('STAGE_FORBIDDEN',[d['code'] for d in denied['diagnostics']])
        def verify(actual,out):
            self.assertEqual(actual['public_stats'],task['datasets'][0]['stats'])
            if impl=='sample':
                self.assertEqual(actual['source_ordinals'],[1,3,5,8,18])
                self.assertEqual(actual['sample'],[{'id':i} for i in [1,3,5,8,18]])
            else:self.assertNotIn('sample',actual)
            return {'status':'PASS','recipe':'literal reservoir golden; metadata public-only'}
        _,events=self.run_bound(task,plan.value,path,None,'stats:'+impl,stage='generation_probe',verifier=verify)
        ledger=[e['payload'] for e in events if e['event_kind']=='generation_probe'];self.assertEqual(len(ledger),1)
        self.assertEqual(ledger[0]['source_rows_read'],37 if impl=='sample' else 0)
        self.assertEqual(ledger[0]['logical_read_bytes'],37*8 if impl=='sample' else 0)
    def test_stats_metadata(self):self.stats('metadata')
    def test_stats_sample(self):self.stats('sample')

    def test_dense_fixed_actual_encoding_and_exact_dot(self):
        from rcwg_full.data.dense import prepare_dense
        from rcwg_full.runtime.dense_encoder import PROFILE
        from rcwg_full.data.document_templates import document_descriptor,DOMAIN,REVISION
        from rcwg_full.runtime.documents import canonical_document
        docs=[canonical_document(str(i),REVISION,'',[{'text':text}]) for i,text in enumerate(['red red','blue','red blue'])]
        model={'profile':PROFILE,'model_id':'engineering-red-blue-mean-v1','dimension':2,'normalize':False,
            'weights':{'red':[1.,0.],'blue':[0.,1.]},'oov':[0.,0.],
            'provenance':{'origin':'HAND_AUTHORED_ENGINEERING_WEIGHTS','license':'fixture authored for this test','source_revision':'fixture-v1'}}
        task=task_shell('F5-01',0,'C0','Exact dot product retrieval',{'id':'result','type':'id_set','mode':'exact','item_type':'Utf8','domain':DOMAIN,'revision':REVISION})
        task['datasets']=[document_descriptor('documents',docs)]
        task,_,path=prepare_dense(task,{'dataset:documents':docs},{'dataset:documents':model},self.root/'data')
        plan=Plan(task['task_id']);plan.value['external_inputs']['documents']='dataset:documents'
        result=plan.add('retrieve','text_retrieve','dense_fixed',{'index':'$input.documents'},{'query':'red','limit':3},{'ids':'RankedIDSet'})
        plan=plan.end(result)
        _,events=self.run_bound(task,plan,path,[{'document_id':'0','score':1.},{'document_id':'2','score':.5},{'document_id':'1','score':0.}], 'text_retrieve:dense_fixed')
        event=next(e['payload'] for e in events if e['event_kind']=='dense_query')
        self.assertGreater(event['query_encoding_elapsed_ns'],0);self.assertEqual(event['query_tokens'],1)
        self.assertEqual(event['origin'],'HAND_AUTHORED_ENGINEERING_WEIGHTS');self.assertTrue(event['encoding_in_execution_clock'])
