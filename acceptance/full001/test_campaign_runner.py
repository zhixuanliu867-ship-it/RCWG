from copy import deepcopy
import json
from pathlib import Path
import unittest
from rcwg_full.evidence import digest,read,write
from rcwg_full.campaign.runner import CampaignRunner,ordered_slots
from rcwg_full.campaign.planning import rebind_frozen
from rcwg_full.campaign.store import CampaignStore,Conflict
from rcwg_full.compiler import FullCompiler
from rcwg_full.data.templates import f1
from support import EvidenceDirectory


def slots():
    base={'family':'F1','condition':'C0','task_id':'F1-01-b0-C0','template_id':'F1-01','base_id':0,'generator':'G0','protocol':'P1','trial_label':17,'ledger_role':'PRIMARY','experiment_id':'E1'}
    return [{**base,'slot_id':'generation','slot_kind':'generation','expected_dependencies':[]},
            *[{**base,'slot_id':f'exec-{i}','slot_kind':'execution','execution_repeat':i,'generation_slot_id':'generation','expected_dependencies':['generation']} for i in range(3)]]


class CampaignRunnerTests(unittest.TestCase):
    def setUp(self):self.evidence=EvidenceDirectory('runner-'+digest(self.id())[:16]);self.root=Path(self.evidence.name)
    def tearDown(self):self.evidence.cleanup()
    def runner(self,generation,execution,*,resume=False,mode='ENGINEERING_REPLAY'):
        return CampaignRunner(self.root/'campaign',slots(),manifest_hash='a'*64,spec_hash='b'*64,mode=mode,generate=generation,execute=execution,resume=resume)

    def test_upstream_failure_retains_all_unrun_denominators(self):
        calls=[]
        runner=self.runner(lambda *args:{'status':'MODEL_FAILURE','failure_class':'CONFIRMED_PLAN'},lambda *args:calls.append(args))
        try:
            result=runner.run();observations=runner.store.observations('ENGINEERING_REPLAY')
        finally:runner.close()
        self.assertEqual(result['status'],'TERMINAL');self.assertEqual(len(observations),4);self.assertEqual(calls,[])
        child=[r for r in observations if r['slot_kind']=='execution'];self.assertEqual(len(child),3)
        self.assertTrue(all(r['status']=='NOT_RUN_UPSTREAM_PLAN_FAILURE' and r['exec_elapsed_ns'] is None and r['physical_attempt'] is False for r in child))

    def test_uncertain_request_pauses_and_resume_never_restarts_it(self):
        sent=[]
        def generation(*args):sent.append(True);return {'status':'SENT_UNCONFIRMED'}
        runner=self.runner(generation,lambda *args:self.fail('execution started'))
        try:first=runner.run()
        finally:runner.close()
        runner=self.runner(generation,lambda *args:self.fail('execution started'),resume=True)
        try:second=runner.run();state=runner.store.reconcile()
        finally:runner.close()
        self.assertEqual(len(sent),1);self.assertEqual(first['status'],'PAUSED_RECONCILIATION')
        self.assertEqual(second['paused'][0]['reason'],'RECONCILE_REQUIRED');self.assertEqual(sum(r['status']=='NOT_RUN' for r in state),3)
        with self.assertRaisesRegex(ValueError,'RESUME_IDENTITY'):self.runner(generation,lambda *args:None,resume=True,mode='FORMAL')

    def test_persisted_plan_evidence_is_used_and_finished_slots_are_immutable(self):
        plan=f1('F1-01',0,'C0')['plan'];seen=[]
        def execute(slot,attempt,deps,directory):
            self.assertEqual(deps['generation']['plan'],plan);seen.append(slot['execution_repeat'])
            return {'status':'COMPLETED','semantic':True,'budget':None,'evidence_valid':True,'timing_valid':False,'protocol_fixture_only':True}
        runner=self.runner(lambda *args:{'status':'COMPLETED','plan':plan,'plan_hash':digest(plan)},execute)
        try:result=runner.run()
        finally:runner.close()
        runner=self.runner(lambda *args:self.fail('regenerated'),execute,resume=True)
        try:resumed=runner.run()
        finally:runner.close()
        self.assertEqual(seen,[0,1,2]);self.assertEqual(result['status'],'TERMINAL');self.assertEqual(resumed['actual_attempts_this_invocation'],[])

    def test_diagnostic_attempt_keeps_role_and_unknown_requires_reconciliation(self):
        store=CampaignStore(self.root/'roles.sqlite3')
        try:
            store.register([{'slot_id':'s','ledger_role':'DIAGNOSTIC'}]);claim=store.claim('s','w','key')
            version=store.mark('s',claim['attempt_id'],'w',claim['version'],'UNKNOWN',{})
            self.assertEqual(store.observations('ENGINEERING_REPLAY')[0]['ledger_role'],'DIAGNOSTIC')
            with self.assertRaisesRegex(Conflict,'RECONCILIATION'):store.mark('s',claim['attempt_id'],'w',version,'COMPLETED',{})
            store.mark('s',claim['attempt_id'],'w',version,'INFRA_FAILURE',{'reconciliation':{'worker_stopped':True,'request_uncertain':False}})
        finally:store.close()

    def test_e2_compiles_target_with_unchanged_c0_plan(self):
        source=f1('F1-01',0,'C0');target=f1('F1-01',0,'C2');plan=source['plan'];before=digest(plan)
        common={'template_id':'F1-01','base_id':0,'generator':'G0','protocol':'P1','trial_label':17}
        binding=rebind_frozen(plan,{**common,'condition':'C0','task_id':source['task']['task_id']},{**common,'condition':'C2','task_id':target['task']['task_id']})
        report=FullCompiler().compile(target['task'],plan,frozen_binding=binding)
        self.assertEqual(report['status'],'IR_VALIDATED');self.assertFalse(report['plan_rewritten']);self.assertEqual(before,digest(plan))
        self.assertEqual(report['task_input_hash'],digest(target['task']));bad=deepcopy(binding);bad['source_binding']['trial_label']=29
        with self.assertRaisesRegex(ValueError,'FROZEN_TARGET'):FullCompiler().compile(target['task'],plan,frozen_binding=bad)

    def test_predeclared_order_does_not_depend_on_observations(self):
        planned=slots()+[{**s,'slot_id':s['slot_id']+'p0','protocol':'P0'} for s in slots()]
        forward=ordered_slots(planned);reverse=ordered_slots(list(reversed(planned)))
        self.assertEqual([s['slot_id'] for s in forward],[s['slot_id'] for s in reverse])
        self.assertEqual([s['slot_kind'] for s in forward[:2]],['generation','generation'])

    def test_all_diagnostic_dependencies_bind_predeclared_primary_slots(self):
        from rcwg_full.campaign.planning import primary_slots,diagnostic_slots
        from rcwg_full.evidence import ROOT
        spec=json.loads(read(ROOT/'specs/full001/campaign.json'));primary=list(primary_slots(spec))
        diagnostic=[s for experiment in ['E2','E3','E4','E7'] for s in diagnostic_slots(experiment)]
        all_rows=primary+diagnostic;known={r['slot_id'] for r in all_rows}
        self.assertTrue(all(d in known for r in all_rows for d in r['expected_dependencies']))
        order={r['slot_id']:i for i,r in enumerate(ordered_slots(all_rows))}
        self.assertTrue(all(order[d]<order[r['slot_id']] for r in all_rows for d in r['expected_dependencies']))
        self.assertEqual(sum(r['slot_kind']=='generation' for r in primary),23040)
        self.assertEqual(sum(r['slot_kind']=='execution' for r in primary),61440)

    def test_one_facility_retry_uses_same_plan_and_retains_both_attempts(self):
        plan=f1('F1-01',0,'C0')['plan'];calls=[]
        def action(slot,attempt,deps,directory):
            self.assertEqual(deps['generation']['plan'],plan);calls.append(attempt)
            native=directory/'native';native.mkdir()
            report={'run_id':attempt,'terminal_status':'INFRA_FAILURE','process_group_final':{'live':[],'zombie':[]},
                'cleanup_failures':[],'paid_calls':0}
            report_hash=write(native/'report.json',report)
            write(native/'seal.json',{'run_id':attempt,'status':'SEALED','files':{'report.json':report_hash}})
            return {'status':'INFRA_FAILURE','failure_class':'INFRASTRUCTURE','plan_hash':digest(plan)}
        runner=self.runner(lambda *a:{'status':'COMPLETED','plan':plan,'plan_hash':digest(plan)},action)
        try:
            first=runner.run();self.assertEqual(first['actual_attempts_this_invocation'][-1]['status'],'INFRA_FAILURE')
            second=runner.retry_failed_execution('exec-0');self.assertEqual(len(calls),2);self.assertNotEqual(*calls)
            records=[r for r in runner.store.observations('ENGINEERING_REPLAY') if r['slot_id']=='exec-0']
            self.assertEqual([r['ledger_role'] for r in records],['PRIMARY','INFRA_RETRY'])
            self.assertEqual(records[1]['parent_attempt_id'],records[0]['attempt_id'])
            self.assertEqual(records[1]['reconciliation'],{'worker_stopped':True,'request_uncertain':False})
            self.assertEqual(records[0]['plan_hash'],records[1]['plan_hash'])
            with self.assertRaisesRegex(Conflict,'RETRY_LIMIT'):runner.retry_failed_execution('exec-0')
            with self.assertRaisesRegex(Conflict,'NOT_ALLOWED'):runner.retry_failed_execution('generation')
            self.assertEqual(runner.store.slot('exec-1')['status'],'NOT_RUN')
        finally:runner.close()

    def test_uncertain_service_or_live_descendant_denies_retry(self):
        def failure(slot,attempt,deps,directory):
            native=directory/'native';native.mkdir()
            report={'run_id':attempt,'terminal_status':'INFRA_FAILURE','process_group_final':{'live':[123]},'cleanup_failures':[],
                'paid_calls':None,'semantic_requests':{'inflight':1,'failures':0,'requests':1,'responses':0}}
            h=write(native/'report.json',report);write(native/'seal.json',{'run_id':attempt,'status':'SEALED','files':{'report.json':h}})
            return {'status':'INFRA_FAILURE'}
        runner=self.runner(lambda *a:{'status':'COMPLETED'},failure)
        try:
            runner.run()
            with self.assertRaisesRegex(Conflict,'PROCESS_NOT_RECONCILED'):runner.retry_failed_execution('exec-0')
            self.assertEqual(runner.store.db.execute("SELECT COUNT(*) FROM attempts WHERE slot_id='exec-0'").fetchone()[0],1)
        finally:runner.close()
