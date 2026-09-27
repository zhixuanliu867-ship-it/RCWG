"""An unresolved facility cannot cause later live comparisons to be dispatched."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile,unittest,json
from rcwg_full.auto2.pipeline import Pipeline


class PipelineStops(unittest.TestCase):
    def exercise(self,status,where):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'PREPARATION_EVIDENCE.json').write_text('{}')
            p=Pipeline.__new__(Pipeline);p.root=root;p.config={'measurement_profile':'SERVICE_ONLY'}
            p.plan={'initial_generations':[{'id':'first','generator':'G0','executions':[{'id':'first-exec'}]},
                {'id':'later','generator':'G0','executions':[]}],
                'initial_semantic_references':[],'development_blocks':[]}
            events=[];sent=[]
            p.state=SimpleNamespace(summary=lambda:{'state':'LIVE_RUNNING'},transition=lambda state,detail:events.append((state,detail)))
            p.current_identity=lambda:{};p.scope=lambda *a,**k:{}
            p.capability=lambda *a:{'status':'COMPLETED','http_status':200}
            def generate(job,scope):
                sent.append(job['id']);record={'status':status if where=='generation' else 'COMPLETED','plan':{}}
                p.save_once('private/generations/'+job['id']+'.json',record);return record
            def execute(job,*args,**kwargs):
                sent.append(job['id']);record={'status':status}
                p.save_once('private/executions/'+job['id']+'.json',record);return record
            p.generation=generate;p.execution=execute
            with patch('rcwg_full.auto2.pipeline.preparation_gate',return_value={'status':'PASS'}):
                with self.assertRaisesRegex(PermissionError,'ACTUAL_FACILITY_REQUIRES_RECONCILIATION'):p.run()
            self.assertNotIn('later',sent)
            self.assertEqual(events[-1][0],'PAUSED_EXTERNAL')
            self.assertFalse(events[-1][1]['provider_retry_permitted'])
            expected='private/generations/first.json' if where=='generation' else 'private/executions/first-exec.json'
            self.assertEqual(json.loads((root/expected).read_bytes())['status'],status)

    def test_uncertain_generation_stops_before_worker_and_later_requests(self):
        self.exercise('SENT_UNCONFIRMED','generation')

    def test_version_drift_stops_before_later_comparison(self):
        self.exercise('SERVICE_DRIFT','generation')

    def test_worker_facility_failure_stops_later_requests(self):
        self.exercise('INFRA_FAILURE','execution')

    def test_confirmed_plan_errors_are_not_facility_blockers(self):
        p=Pipeline.__new__(Pipeline)
        for status in ['MODEL_FAILURE','PLAN_INVALID','TIMEOUT','OOM','NOT_RUN','COMPLETED']:
            p.require_resolved_facility({'status':status},'job')
