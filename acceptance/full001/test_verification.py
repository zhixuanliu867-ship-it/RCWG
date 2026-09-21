"""Explicit wrong-answer and legal-equivalence cases, independent of kernel code."""
from copy import deepcopy
from pathlib import Path
import os
import unittest
import tempfile
from rcwg_full.evidence import write
from rcwg_full.verification.compare import check_output,check_paths,bag_equal
from rcwg_full.verification.semantic import verify_semantics,evidence_metrics,information_fidelity
from rcwg_full.verification.layers import check_complete_journal
from rcwg_full.runtime.events import Journal


def graph_case(v):
    return {'directed':True,'domain':'graph-'+str(v),'revision':'r1','nodes':[{'node_id':i+v*10} for i in range(4)],'edges':[
        {'edge_id':str(v)+'-'+str(i),'src':a+v*10,'dst':b+v*10,'weight':1.0} for i,(a,b) in enumerate([(0,1),(1,3),(0,2),(2,3)])]}


def path_case(v,alternate=False):
    return [{'target':v*10+3,'reachable':True,'distance':2.0,'nodes':[v*10,v*10+(2 if alternate else 1),v*10+3],'edges':[str(v)+'-'+str(i) for i in ([2,3] if alternate else [0,1])]}]


def semantic_case(v):
    citation={'document_id':'doc-'+str(v),'revision':'r1','start_cp':10,'end_cp':20,'quote':'0123456789'}
    fields={'status':{'acceptable_values':['refuted'],'critical':True},'date':{'acceptable_values':['2026-01-'+str(v+1).zfill(2)],'critical':True},'unit':{'acceptable_values':['mg'],'critical':True}}
    recipe={'fields':fields,'exact_fields':True,'evidence_obligations':[{'id':'q','acceptable_witness_sets':[[citation]]}]}
    actual={'fields':{k:f['acceptable_values'][0] for k,f in fields.items()},'evidence':[citation]}
    return actual,recipe


def wrong_case(category,v):
    expected=[{'id':v*10+i,'value':i} for i in range(4)];actual=deepcopy(expected);contract={'comparison':'bag'}
    if category=='omission':actual.pop()
    elif category=='addition':actual.append({'id':1000+v,'value':1})
    elif category=='ordering':actual.reverse();contract={'comparison':'ordered'}
    elif category=='duplicate_set':return lambda:check_output([v,v],[v],{'comparison':'set'})['status']=='PASS'
    elif category=='null':return lambda:check_output({'id':v,'x':0},{'id':v,'x':None},{'comparison':'record'})['status']=='PASS'
    elif category=='join_multiplicity':expected=expected+deepcopy(expected);actual=actual+deepcopy(actual[:-1])
    elif category in {'direction','weight','unreachable'}:
        graph=graph_case(v);paths=path_case(v)
        if category=='direction':paths[0]['nodes']=[v*10+3,v*10+1,v*10]
        elif category=='weight':paths[0]['distance']=1.0
        else:paths[0].update(reachable=False,distance=None,nodes=[],edges=[])
        return lambda:check_paths(paths,graph,[v*10],[v*10+3],weight_field='weight')[0]
    elif category=='induced_edge':
        expected=graph_case(v);actual=deepcopy(expected);actual['edges'].pop();contract={'comparison':'graph'}
    elif category in {'document','negation','date','unit','conflict','span','revision'}:
        actual,recipe=semantic_case(v)
        if category=='document':actual['evidence'][0]['document_id']='foreign-'+str(v)
        elif category in {'negation','conflict'}:actual['fields']['status']='supported' if category=='negation' else 'unknown'
        elif category=='date':actual['fields']['date']='2025-01-'+str(v+1).zfill(2)
        elif category=='unit':actual['fields']['unit']='g'
        elif category=='span':actual['evidence'][0]['start_cp']=11;actual['evidence'][0]['end_cp']=21
        else:actual['evidence'][0]['revision']='unavailable-r2'
        # Recipe labels are independent objects, not mutated together with the result.
        _,recipe=semantic_case(v)
        return lambda:verify_semantics(actual,recipe)['status']=='PASS'
    elif category=='missing_result':actual=None
    elif category=='boolean_integer':return lambda:check_output(v+1,True,{'comparison':'scalar'})['status']=='PASS'
    elif category=='incomplete_witness':
        actual,recipe=semantic_case(v);actual['evidence']=[]
        return lambda:verify_semantics(actual,recipe)['status']=='PASS'
    elif category=='incomplete_ledger':
        def accepted():
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'events.jsonl';j=Journal(p,'mutation-'+str(v));j.append('run_started',{});j.close()
                try:check_complete_journal(p)
                except ValueError:return False
                return True
        return accepted
    return lambda:check_output(actual,expected,contract)['status']=='PASS'


def equivalent_case(category,v):
    if category=='set_order':return lambda:check_output(list(reversed(range(v+3))),list(range(v+3)),{'comparison':'set'})['status']=='PASS'
    if category=='bag_order':return lambda:check_output([v,2,v,1],[1,v,v,2],{'comparison':'bag'})['status']=='PASS'
    if category=='graph_order':
        expected=graph_case(v);actual=deepcopy(expected);actual['nodes'].reverse();actual['edges'].reverse()
        return lambda:check_output(actual,expected,{'comparison':'graph'})['status']=='PASS'
    if category in {'equal_shortest_path','coherent_node_rename'}:
        graph=graph_case(v);actual=path_case(v,True)
        if category=='coherent_node_rename':
            rename=lambda i:'node-'+str(i)
            for n in graph['nodes']:n['node_id']=rename(n['node_id'])
            for e in graph['edges']:e['src']=rename(e['src']);e['dst']=rename(e['dst'])
            for p in actual:p['nodes']=[rename(n) for n in p['nodes']];p['target']=rename(p['target'])
            return lambda:check_paths(actual,graph,[rename(v*10)],[rename(v*10+3)],weight_field='weight')[0]
        return lambda:check_paths(actual,graph,[v*10],[v*10+3],weight_field='weight')[0]
    if category=='numeric_rounding':return lambda:check_output({'v':float(v)+1e-9},{'v':float(v)},{'comparison':'record'})['status']=='PASS'
    actual,recipe=semantic_case(v)
    if category=='duplicate_citation':actual['evidence']*=2
    elif category=='split_citation':
        citation=actual['evidence'][0];actual['evidence']=[dict(citation,end_cp=15,quote='01234'),dict(citation,start_cp=15,quote='56789')]
    elif category=='acceptable_alternative':recipe['fields']['status']['acceptable_values'].append('contradicted');actual['fields']['status']='contradicted'
    elif category=='witness_alternative':
        other=dict(actual['evidence'][0],start_cp=30,end_cp=40);recipe['evidence_obligations'][0]['acceptable_witness_sets'].append([other]);actual['evidence']=[other]
    return lambda:verify_semantics(actual,recipe)['status']=='PASS'


class Mutations(unittest.TestCase):pass
class Equivalences(unittest.TestCase):pass


def install(cls,prefix,category,variant,constructor,expected):
    name='test_'+prefix+'_'+category+'_'+str(variant).zfill(2)
    def test(self):
        operation=constructor(category,variant);actual=operation()
        root=os.environ.get('RCWG_FULL_TEST_EVIDENCE')
        if root:
            out=Path(root)/self.id();out.mkdir(parents=True,exist_ok=False)
            write(out/'CASE_RESULT.json',{'case_id':self.id(),'category':category,'variant':variant,'expected_accept':expected,'actual_accept':actual,'status':'PASS' if actual==expected else 'FAIL'})
            inputs={name:cell.cell_contents for name,cell in zip(operation.__code__.co_freevars,operation.__closure__ or ()) if not callable(cell.cell_contents)}
            write(out/'CASE_INPUTS.json',{'category':category,'variant':variant,'fixture_inputs':inputs})
        self.assertEqual(actual,expected,self.id())
    setattr(cls,name,test)

for category in ['omission','addition','ordering','duplicate_set','null','join_multiplicity','direction','weight','unreachable','induced_edge','document','negation','date','unit','conflict','span','revision','missing_result','boolean_integer','incomplete_witness','incomplete_ledger']:
    for variant in range(5):install(Mutations,'reject',category,variant,wrong_case,False)
for category in ['set_order','bag_order','graph_order','equal_shortest_path','coherent_node_rename','numeric_rounding','duplicate_citation','split_citation','acceptable_alternative','witness_alternative']:
    for variant in range(10):install(Equivalences,'accept',category,variant,equivalent_case,True)


class VerificationBoundaries(unittest.TestCase):
    def test_tolerant_bag_requires_global_matching(self):
        self.assertTrue(bag_equal([1e-8,2e-8],[0.0,1e-8],abs_tol=1.01e-8,rel_tol=0))
    def test_no_evidence_is_not_perfect_precision(self):
        self.assertIsNone(evidence_metrics([],[])['precision'])
        _,recipe=semantic_case(0);m=evidence_metrics([],recipe['evidence_obligations'])
        self.assertIsNone(m['precision']);self.assertEqual(m['recall'],0)
    def test_fidelity_keeps_future_recovery_separate(self):
        obligations=[{'id':'q','acceptable_witness_sets':[['definition','value'],['self-contained']]}]
        r=information_fidelity(['value'],obligations,recoverable_units=['definition'])
        self.assertEqual(r['coverage'],0);self.assertEqual(r['potentially_recoverable'],['q']);self.assertFalse(r['permanent_loss_claimed'])
