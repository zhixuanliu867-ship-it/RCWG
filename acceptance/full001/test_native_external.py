"""Native API contract tests use explicit doubles, never original-run claims."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,unittest
from rcwg_full.evidence import write,read,digest
from rcwg_full.reference.native_external import registry,validate_job,dispatch,run_admitted,tps_definitions


def jobs():
    return {'TPS-Bench':{'logs':['<query>q</query><tool_selection>x</tool_selection>'],'tools':{'tools':[]}},
      'WorFEval':{'metric':'graph','predicted':{'nodes':['a'],'edges':[]},'expected':{'nodes':['a'],'edges':[]},'embedding_model':{'local_path':'weights','files':{'model':'a'*64}}},
      'SemBench':{'scenario':'movie','scale_factor':1,'query_ids':[1,3],'model':'fixture','policy':'approximate','ranking':'map','concurrent_llm_worker':1},
      'LOTUS':{'rows':[{'text':'x'}],'model':{'model':'fixture'},'steps':[{'operator':'sem_extract','arguments':{'input_cols':['text'],'output_cols':{'value':'meaning'},'extract_quotes':True}},{'operator':'sem_join','arguments':{'join_instruction':'{text:left} matches {text:right}','right_rows':[{'text':'x'}]}}]},
      'DocETL':{'config':{'datasets':{},'operations':[],'pipeline':{'steps':[],'output':{'type':'file','path':'unused.json'}}},'max_threads':1}}


class NativeExternal(unittest.TestCase):
    def test_five_exact_pins_have_native_source_and_dependency_evidence(self):
        entries=registry()['tracks'];self.assertEqual(set(entries),set(jobs()))
        for name,entry in entries.items():
            with self.subTest(track=name):
                self.assertRegex(entry['revision'],'^[0-9a-f]{40}$')
                self.assertIn(entry['entrypoint'],entry['files'])
                self.assertTrue('requirements.txt' in entry['files'] or 'uv.lock' in entry['files'])
                self.assertEqual(entry['actual_native_runs'],0)
                self.assertEqual(validate_job(name,jobs()[name]),jobs()[name])

    def test_all_five_native_call_shapes_and_results(self):
        calls=[]
        def tps(prompt,log_file_path,available_tools_path,output_path):
            calls.append(('tps',len(list(Path(log_file_path).glob('*.log')))))
            write(output_path,b'{"response":{"total_score":71}}\n')
        class Runner:
            def __init__(self,*,use_case,scale_factor,model_name,concurrent_llm_worker):calls.append(('sembench',use_case,scale_factor,model_name,concurrent_llm_worker))
            def execute_queries(self,query_ids):return {q:{'query_id':q,'status':'success'} for q in query_ids}
        class Frame:
            def __init__(self,rows):self.rows=rows
            def sem_extract(self,*,input_cols,output_cols,extract_quotes):calls.append(('extract',input_cols,output_cols,extract_quotes));return self
            def sem_join(self,other,join_instruction):calls.append(('join',other.rows,join_instruction));return self
        @contextmanager
        def context(*,lm,enable_cache):
            self.assertEqual(lm,'fixture-lm');self.assertFalse(enable_cache);yield
        class DSL:
            def __init__(self,config,*,max_threads):calls.append(('docetl',max_threads));self.total_token_usage={'fixture':{'prompt_tokens':7}}
            def load(self):calls.append(('load',))
            def run(self):return [{'value':4}],0.125
        def graph(pred,expected,model):calls.append(('graph',pred,expected,model));return {'f1_score':1.0}
        backends={'TPS-Bench':{'SYSTEM_PROMPT':'fixture','generate_with_gemini_eval':tps},
            'WorFEval':{'module':SimpleNamespace(t_eval_graph=graph),'embedding_model':'local-only'},
            'SemBench':{'runner_class':Runner},'LOTUS':{'pandas':SimpleNamespace(DataFrame=Frame),'lotus':SimpleNamespace(settings=SimpleNamespace(context=context)),'lm':'fixture-lm'},
            'DocETL':{'runner_class':DSL}}
        with tempfile.TemporaryDirectory() as tmp:
            results={}
            for track,job in jobs().items():
                output=Path(tmp)/track;output.mkdir();results[track]=dispatch(track,job,backends[track],output)
            self.assertEqual(results['TPS-Bench'][0]['response']['total_score'],71)
            self.assertEqual(results['WorFEval']['f1_score'],1.)
            self.assertEqual(set(results['SemBench']),{1,3})
            self.assertEqual(results['LOTUS'].rows,[{'text':'x'}])
            self.assertEqual(results['DocETL']['upstream_token_usage']['fixture']['prompt_tokens'],7)
            self.assertEqual(results['DocETL']['upstream_cost'],.125)
        self.assertEqual(len(calls),7)

    def test_no_import_before_admission_and_claim_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job=jobs()['WorFEval'];identity={'checkout':str(root),'revision':'r'}
            receipt={'attempt_id':'a1','job_sha256':digest(job),'runtime_sha256':digest(identity),'claim_directory':str(root/'claims'),'input_files':{}}
            with patch('rcwg_full.reference.native_external.verify_checkout',return_value=identity),patch('rcwg_full.reference.native_external._native_backend') as load:
                with self.assertRaises(PermissionError):run_admitted('WorFEval',job,checkout=root,environment={},receipt=receipt,admit=lambda r:False,output=root/'denied')
                load.assert_not_called();self.assertFalse((root/'claims').exists())
                load.side_effect=RuntimeError('offline dependency fixture')
                result=run_admitted('WorFEval',job,checkout=root,environment={},receipt=receipt,admit=lambda r:True,output=root/'failed')
                self.assertEqual(result['status'],'INFRA_OR_UPSTREAM_FAILURE');self.assertIsNone(result['paid_call_count'])
                with self.assertRaises(FileExistsError):run_admitted('WorFEval',job,checkout=root,environment={},receipt=receipt,admit=lambda r:True,output=root/'again')
                self.assertEqual(load.call_count,1)

    def test_upstream_unsupported_knobs_and_top_level_side_effects_are_rejected_or_excluded(self):
        job=jobs()['SemBench'];job['policy']='exact'
        with self.assertRaisesRegex(ValueError,'DEFAULTS'):validate_job('SemBench',job)
        job=jobs()['LOTUS'];job['steps'][1]['arguments']['user_instruction']='wrong upstream keyword'
        with self.assertRaisesRegex(ValueError,'ARGUMENTS'):validate_job('LOTUS',job)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'upstream.py';p.write_text('raise RuntimeError("IMPORT_MUST_NOT_RUN")\nSYSTEM_PROMPT="fixture"\ndef extract_query_and_tools(*args): return args\ndef clean_response(s): return s\ndef generate_with_gemini_eval(*args): return args\n',encoding='utf8')
            namespace=tps_definitions(p);self.assertEqual(namespace['clean_response']('offline'),'offline')


if __name__=='__main__':unittest.main()
