"""R2 source ingestion and durable candidate identity regression proofs."""
from copy import deepcopy
import json
import unittest
from rcwg_full.data.templates import f1
from rcwg_full.data.upstream import qasper
from rcwg_full.evidence import canonical,digest
from rcwg_full.reference.candidates import candidates,decision_identity


class ReviewR2(unittest.TestCase):
    def test_candidate_ids_survive_canonical_storage_with_multiple_sources(self):
        d=f1('F1-08',0,'C0');generated=candidates(d['task'],d['plan'])
        stored=json.loads(canonical(generated))
        for candidate in stored['candidates']:
            self.assertEqual(candidate['candidate_id'],decision_identity(candidate['plan']))
            self.assertEqual(candidate['plan_hash'],digest(candidate['plan']))
        self.assertEqual(len({c['candidate_id'] for c in stored['candidates']}),len(stored['candidates']))

    def test_external_alias_rename_reorder_and_real_source_swap(self):
        plan=f1('F1-08',0,'C0')['plan'];other=deepcopy(plan)
        names={name:'alias'+str(10-i) for i,name in enumerate(other['external_inputs'])}
        other['external_inputs']={names[k]:v for k,v in reversed(list(other['external_inputs'].items()))}
        for node in other['nodes']:
            node['inputs']={k:'$input.'+names[v[7:]] if v.startswith('$input.') else v for k,v in node['inputs'].items()}
        self.assertEqual(decision_identity(plan),decision_identity(other))
        keys=list(other['external_inputs']);other['external_inputs'][keys[0]],other['external_inputs'][keys[1]]=other['external_inputs'][keys[1]],other['external_inputs'][keys[0]]
        self.assertNotEqual(decision_identity(plan),decision_identity(other))

    def test_region_capture_order_and_renaming_are_not_decisions(self):
        # A structural identity example with two captures and distinct edges.
        plan={'task_id':'x','external_inputs':{'right':'dataset:r','left':'dataset:l'},'nodes':[
          {'id':'loop','operator':'map','inputs':{},'regions':{'body':{'bindings':{'z':'$input.right','a':'$input.left'},
           'nodes':[{'id':'consume','inputs':{'left':'$bound.a','right':'$bound.z'}}],'yield':{'rows':'consume.rows'}}}}], 'result':'loop.rows'}
        other=json.loads(canonical(plan));r=other['nodes'][0]['regions']['body']
        r['bindings']={'renamed_right':r['bindings']['z'],'renamed_left':r['bindings']['a']}
        r['nodes'][0]['inputs']={'left':'$bound.renamed_left','right':'$bound.renamed_right'}
        self.assertEqual(decision_identity(plan),decision_identity(other))
        r['nodes'][0]['inputs']['left']='$bound.renamed_right'
        self.assertNotEqual(decision_identity(plan),decision_identity(other))

    def test_real_qasper_null_heading_preserves_text_original_and_spans(self):
        source={'p':{'title':'Title','abstract':'','full_text':[{'section_name':None,'paragraphs':['Evidence 🙂.']}],
         'qas':[{'question_id':'q','question':'Question?','answers':[{'answer':{'unanswerable':False,'yes_no':None,'extractive_spans':['Evidence'],'evidence':['Evidence 🙂.']}}]}]}}
        before=deepcopy(source);license={'license_text_sha256':'0'*64,'redistribution_policy':'PRIVATE_REVIEW','annotation_provenance':'original'}
        bundle=qasper(source,upstream_revision='qasper-v0.3-null-heading-regression',license_record=license)
        doc=bundle['public']['documents'][0];span=bundle['private']['annotations'][0]['acceptable_annotations'][0]['evidence'][0]['candidates'][0]
        self.assertEqual(source,before);self.assertEqual(bundle['private']['original_source'],before)
        self.assertEqual(doc['metadata']['null_heading_sections'],[0]);self.assertEqual(doc['sections'][0]['heading'],'')
        self.assertEqual(doc['canonical_text'][span['start_cp']:span['end_cp']],'Evidence 🙂.')
        source['p']['full_text'][0]['section_name']=17
        with self.assertRaisesRegex(ValueError,'SOURCE_TEXT_TYPE'):qasper(source,upstream_revision='r',license_record=license)
