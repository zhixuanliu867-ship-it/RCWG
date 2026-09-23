"""Hand-authored upstream-shaped fixtures exercise real-source binding software.

These fixture records are not downloaded QASPER/SciFact data or human labels.
"""
from copy import deepcopy
import json,tempfile,unittest
from pathlib import Path
from rcwg_full.data.formal_documents import bind_candidate,contracts,section_view,remap_citation
from rcwg_full.data.document_templates import f5
from rcwg_full.data.mixed_templates import f6
from rcwg_full.data.upstream import qasper,scifact
from rcwg_full.verification.document_oracle import f5_expected,verify_rows
from rcwg_full.verification.mixed_oracle import f6_expected
from rcwg_full.verification.prepared import check_prepared
from rcwg_full.evidence import digest

LICENSE={'license_text_sha256':None,'redistribution_policy':'ENGINEERING_FIXTURE_NOT_REAL_SOURCE','annotation_provenance':'HAND_AUTHORED_TEST_ONLY'}


def fixture(template,condition='C0'):
    d=(f5 if template.startswith('F5') else f6)(template,0,condition)
    original=d['rows']['documents'];expected=(f5_expected if template.startswith('F5') else f6_expected)(d['expected_args'])
    revision=original[0]['revision']
    if template.startswith('F5'):
        papers={doc['document_id']:{'title':doc['title'],'full_text':[{'section_name':s['heading'],'paragraphs':[s['text']]} for s in doc['sections']],
            'qas':[{'question_id':'q-'+doc['document_id'],'question':d['task']['instruction'],'answers':[]}]} for doc in original}
        bundle=qasper(papers,upstream_revision=revision,license_record=LICENSE)
    else:
        bundle=scifact([{'doc_id':doc['document_id'],'title':doc['title'],'abstract':[s['text'] for s in doc['sections']]} for doc in original],
            [{'id':'q-fixture','claim':d['task']['instruction'],'cited_doc_ids':[doc['document_id'] for doc in original]}],
            upstream_revision=revision,license_record=LICENSE)
    by_id={doc['document_id']:doc for doc in bundle['public']['documents']}
    def remap(value):
        if isinstance(value,dict):
            if {'document_id','revision','start_cp','end_cp','quote'}<=value.keys():
                text=by_id[value['document_id']]['canonical_text'];quote=value['quote'];start=text.index(quote)
                return {**value,'start_cp':start,'end_cp':start+len(quote)}
            return {k:remap(v) for k,v in value.items()}
        if isinstance(value,list):return [remap(v) for v in value]
        return value
    expected=remap(expected)
    # F6-12's deliberately stale synthetic decoy is not imported as real text.
    d['task']['datasets']=[s for s in d['task']['datasets'] if s['id']!='dataset:stale_documents']
    bindings={}
    for source in d['task']['datasets']:
        alias=source['id'].split(':')[1];value=d['rows'][alias]
        if source['kind']=='document_index':binding={'mode':'documents','record_ids':[v['document_id'] for v in value]}
        elif source['kind']=='id_selection':binding={'mode':'ids','record_ids':value}
        else:binding={'mode':'public_literal','construction_rule':'HAND_AUTHORED_PUBLIC_TEST_INPUT','value':value}
        bindings[source['id']]=binding
    contract=contracts()[template];split=contract['split']
    design={'template_id':template,'base_id':0,'condition':condition,'task':d['task'],'plan':d['plan'],'bindings':bindings,
        'contract_sha256':digest(contract),'split_clusters':{split:list(by_id)},
        'source_question_ids':[r['question_id' if template.startswith('F5') else 'claim_id'] for r in bundle['public']['questions' if template.startswith('F5') else 'claims']],
        'condition_claims':{'status':'ENGINEERING_ONLY'}}
    return bundle,design,expected


class FormalDocumentBinding(unittest.TestCase):
    def test_all_24_templates_bind_actual_upstream_shapes_and_private_verifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            for template in contracts():
                with self.subTest(template=template):
                    bundle,design,expected=fixture(template)
                    result=bind_candidate(bundle,design,expected,Path(tmp)/template,reviewers=['fixture-a','fixture-b'],profile='engineering_tiny_v1')
                    self.assertEqual(result['proof']['status'],'IR_VALIDATED')
                    actual=expected['result']
                    if template=='F6-04':continue # paths require an independent full path answer, exercised by native mixed tests
                    self.assertEqual(check_prepared(actual,result['private_verifier'])['status'],'PASS')
                    self.assertNotEqual(check_prepared(None,result['private_verifier'])['status'],'PASS')
                    self.assertFalse(result['binding']['formal_frozen'])
                    self.assertNotIn('expected',json.loads((Path(tmp)/template/'task_public.json').read_text('utf8')))
                    review=json.loads((result['private_directory']/'blind-review/reviewer-1.json').read_text('utf8'))
                    self.assertNotIn('stages',json.dumps(review));self.assertNotIn('fixture-b',json.dumps(review))

    def test_rejects_forged_source_leakage_stale_revision_split_and_missing_stage(self):
        bundle,design,expected=fixture('F5-01')
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ['source','private_injection','revision','split','stage','contract','question']:
                b,d,e=deepcopy(bundle),deepcopy(design),deepcopy(expected)
                if mode=='source':b['public']['documents'][0]['canonical_text']+='forged'
                if mode=='private_injection':b['public']['questions'][0]['answers']=['gold']
                if mode=='revision':d['task']['datasets'][0]['revision']='old'
                if mode=='split':d['split_clusters']['test']=d['split_clusters']['development']
                if mode=='stage':e['stages']={}
                if mode=='contract':d['contract_sha256']='0'*64
                if mode=='question':d['source_question_ids']=['nonexistent']
                with self.subTest(mode=mode),self.assertRaises(ValueError):
                    bind_candidate(b,d,e,Path(tmp)/mode,reviewers=['a','b'])
                self.assertFalse((Path(tmp)/mode).exists())

    def test_source_section_views_remap_unicode_and_reject_lost_witness(self):
        from rcwg_full.runtime.documents import canonical_document
        original=canonical_document('p','r','title',[{'section_id':'a','heading':'A','text':'🙂 proof 5.'},{'section_id':'b','heading':'B','text':'Neutral.'}])
        view,mapping=section_view(original,['b','a'],revision='r-C3')
        a=original['canonical_text'].index('🙂');citation={'document_id':'p','revision':'r','start_cp':a,'end_cp':a+10,'quote':'🙂 proof 5.'}
        mapped=remap_citation(citation,original,view,mapping)
        self.assertEqual(view['canonical_text'][mapped['start_cp']:mapped['end_cp']],'🙂 proof 5.')
        self.assertNotEqual(a,mapped['start_cp'])
        short,short_map=section_view(original,['b'],revision='short')
        with self.assertRaisesRegex(ValueError,'NOT_CONTIGUOUS'):remap_citation(citation,original,short,short_map)

    def test_semantic_duplicates_use_bounded_nonrecursive_matching(self):
        bundle,_,expected=fixture('F5-01');row=expected['result'][0]
        rows=[deepcopy(row) for _ in range(1005)]
        self.assertEqual(verify_rows(rows,rows,bundle['public']['documents'])['status'],'PASS')
        changed=deepcopy(rows);changed[-1]['dose']+=1
        self.assertEqual(verify_rows(changed,rows,bundle['public']['documents'])['status'],'FAIL')


if __name__=='__main__':unittest.main()
