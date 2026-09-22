"""Finite frozen slots, transactional claims and append-only attempt packages."""
from collections import defaultdict,Counter
from pathlib import Path
import json
import random
import heapq
import uuid
import time
from rcwg_full.evidence import digest,read,write,sha,source_hashes,safe_path
from .store import CampaignStore,Conflict
from .sealing import check_expected,relative_file

PAUSE={'UNKNOWN','SENT_UNCONFIRMED','SERVICE_DRIFT','NOT_AUTHORIZED','INFRA_FAILURE'}


def ordered_slots(slots,seed=481013):
    """Prerecorded paired blocks; protocol ordering alternates within each block."""
    rng=random.Random(seed);blocks=defaultdict(list)
    for row in slots:blocks[(row.get('family'),row.get('condition'))].append(row)
    result=[]
    for block in sorted(blocks,key=str):
        groups=defaultdict(list)
        for row in blocks[block]:
            # Keep paired protocols and repeats in the same group. Generations
            # precede their dependent executions; no observation selects order.
            groups[(row.get('task_id'),row.get('generator'),row.get('trial_label'),row.get('experiment_id'))].append(row)
        keys=sorted(groups,key=str);rng.shuffle(keys)
        for index,key in enumerate(keys):
            protocols=['P0','P1'] if index%2==0 else ['P1','P0']
            result.extend(sorted(groups[key],key=lambda r:(0 if r['slot_kind']=='generation' else 1,
                r.get('execution_repeat') if r.get('execution_repeat') is not None else -1,
                protocols.index(r['protocol']) if r.get('protocol') in protocols else 2,r['slot_id'])))
    positions={r['slot_id']:i for i,r in enumerate(result)}
    if len(positions)!=len(result):raise ValueError('DUPLICATE_EXPECTED_SLOT')
    pending={r['slot_id']:set(r.get('expected_dependencies',[]))&positions.keys() for r in result}
    children=defaultdict(list)
    for ident,deps in pending.items():
        for dependency in deps:children[dependency].append(ident)
    ready=[positions[k] for k,v in pending.items() if not v];heapq.heapify(ready);ordered=[]
    while ready:
        row=result[heapq.heappop(ready)];ordered.append(row)
        for child in children[row['slot_id']]:
            pending[child].remove(row['slot_id'])
            if not pending[child]:heapq.heappush(ready,positions[child])
    if len(ordered)!=len(result):raise ValueError('CAMPAIGN_DEPENDENCY_CYCLE')
    return ordered


class CampaignRunner:
    def __init__(self,root,slots,*,manifest_hash,spec_hash,mode,generate,execute,source_identity=None,resume=False,external_dependencies=None,store=None):
        self.root=safe_path(root);self.mode=mode;self.generate=generate;self.execute=execute
        self.identity=source_identity or source_hashes();self.owner='worker-'+str(uuid.uuid4())
        self.external_dependencies=external_dependencies or {}
        if mode not in {'FORMAL','ENGINEERING_NATIVE','ENGINEERING_REPLAY'}:raise ValueError('CAMPAIGN_MODE')
        self.slots={row['slot_id']:row for row in slots}
        if len(self.slots)!=len(slots):raise ValueError('DUPLICATE_EXPECTED_SLOT')
        anchor={'revision':'FULL001_CAMPAIGN_RUN_1','manifest_hash':manifest_hash,'spec_hash':spec_hash,
                'source_identity_hash':digest(self.identity),'mode':mode,'expected_slots_hash':digest(slots),'order_seed':481013,
                'external_dependencies_hash':digest(self.external_dependencies)}
        if resume:
            if json.loads(read(self.root/'run-anchor.json'))!=anchor:raise ValueError('RESUME_IDENTITY_MISMATCH')
        else:
            self.root.mkdir(parents=True,exist_ok=False,mode=0o700);write(self.root/'run-anchor.json',anchor)
            write(self.root/'execution-order.json',{'seed':481013,'slots':[r['slot_id'] for r in ordered_slots(slots)]})
            (self.root/'attempts').mkdir(mode=0o700)
        self.anchor=anchor;self.owns_store=store is None;self.store=store or CampaignStore(self.root/'campaign.sqlite3');self.store.register(slots)
        self.retry_claims={}

    def close(self):
        if self.owns_store:self.store.close()

    def _evidence(self,row):
        if row['status']!='COMPLETED':return None
        attempt=self.store.db.execute('SELECT evidence FROM attempts WHERE id=?',(row['active_attempt'],)).fetchone()
        evidence=json.loads(attempt['evidence'])
        raw=read(relative_file(self.root,evidence['result_file']))
        if sha(raw)!=evidence['result_sha256']:raise ValueError('ATTEMPT_RESULT_CHANGED')
        return json.loads(raw)

    def retry_failed_execution(self,slot_id):
        """One explicit facility retry after sealed process/request evidence.

        This never retries a generation, plan failure, timeout, OOM or an
        uncertain service call. Host and paid handlers recheck their receipts.
        """
        slot=self.store.slot(slot_id)
        if slot['definition']['slot_kind']!='execution' or slot['status']!='INFRA_FAILURE':raise Conflict('RETRY_NOT_ALLOWED')
        if source_hashes()!=self.identity:raise Conflict('RETRY_SOURCE_CHANGED')
        parent=slot['active_attempt'];directory=self.root/'attempts'/parent/'native'
        seal=json.loads(read(directory/'seal.json'))
        if seal.get('status')!='SEALED':raise Conflict('RETRY_UNSEALED_ATTEMPT')
        for name,expected in seal['files'].items():
            if sha(read(relative_file(directory,name)))!=expected:raise Conflict('RETRY_ARTIFACT_CHANGED')
        if 'report.json' not in seal['files']:raise Conflict('RETRY_PROCESS_EVIDENCE_MISSING')
        report=json.loads(read(directory/'report.json'))
        if (report.get('run_id')!=seal['run_id'] or report.get('terminal_status')!='INFRA_FAILURE' or
            report.get('process_group_final',{}).get('live')!=[] or report.get('cleanup_failures')!=[]):raise Conflict('RETRY_PROCESS_NOT_RECONCILED')
        services=report.get('semantic_requests',{})
        if report.get('paid_calls')!=0 and (not services or services.get('inflight')!=0 or
            services.get('failures')!=0 or services.get('requests')!=services.get('responses')):raise Conflict('RETRY_REQUEST_NOT_RECONCILED')
        if report.get('service_reconciliation_required'):raise Conflict('RETRY_REQUEST_NOT_RECONCILED')
        service_root=self.root.parent/'service-evidence'
        if service_root.exists():
            import sqlite3
            for path in service_root.rglob('request-index.sqlite3'):
                with sqlite3.connect(safe_path(path).as_uri()+'?mode=ro',uri=True) as db:
                    if db.execute("SELECT 1 FROM requests WHERE status IN ('PREPARED','SENDING','SENT_UNCONFIRMED') LIMIT 1").fetchone():raise Conflict('RETRY_REQUEST_NOT_RECONCILED')
        reconciliation={'worker_stopped':True,'request_uncertain':False}
        proof={'parent_attempt_id':parent,'seal_file':(directory/'seal.json').relative_to(self.root).as_posix(),
               'seal_sha256':sha(read(directory/'seal.json')),'report_sha256':seal['files']['report.json']}
        claim=self.store.retry(slot_id,self.owner,slot['version'],reconciliation={**reconciliation,'evidence':proof})
        self.retry_claims[slot_id]={**claim,'reconciliation':reconciliation,'reconciliation_evidence':proof}
        return self.run(selected_slots=[slot_id])

    def run(self,*,cancel=lambda:False,selected_slots=None):
        selected=set(self.slots) if selected_slots is None else set(selected_slots)
        if not selected<=self.slots.keys():raise ValueError('SELECTED_SLOT_UNKNOWN')
        actual=[];paused=[]
        for definition in ordered_slots(list(self.slots.values())):
            ident=definition['slot_id'];slot=self.store.slot(ident)
            if ident not in selected:continue
            if cancel():paused.append({'slot_id':ident,'reason':'OWNER_CANCELLED'});break
            if source_hashes()!=self.identity:
                paused.append({'slot_id':ident,'reason':'SOURCE_CHANGED'});break
            retry=self.retry_claims.get(ident)
            if retry and (slot['status']!='CLAIMED' or slot['owner']!=self.owner or slot['active_attempt']!=retry['attempt_id'] or slot['version']!=retry['version']):raise Conflict('RETRY_CLAIM_CHANGED')
            if not retry and slot['status'] in {'CLAIMED','RUNNING','UNKNOWN','SENT_UNCONFIRMED'}:
                paused.append({'slot_id':ident,'reason':'RECONCILE_REQUIRED'});break
            if not retry and slot['status']!='NOT_RUN':continue
            dependencies={};not_ready=False
            for dependency in definition.get('expected_dependencies',[]):
                if dependency in self.external_dependencies:
                    dependencies[dependency]=self.external_dependencies[dependency];continue
                if dependency not in self.slots:raise ValueError('EXPECTED_DEPENDENCY_UNRESOLVED:'+dependency)
                parent=self.store.slot(dependency)
                if parent['status'] in {'MODEL_FAILURE','PLAN_INVALID'}:
                    self.store.upstream_failure(dependency,parent['status']);not_ready=True;break
                if parent['status']!='COMPLETED':
                    paused.append({'slot_id':ident,'reason':'DEPENDENCY_NOT_TERMINAL','dependency':dependency});not_ready=True;break
                dependencies[dependency]=self._evidence(parent)
            if not_ready:
                if paused:break
                continue
            claim=self.retry_claims.pop(ident) if retry else self.store.claim(ident,self.owner,'claim:'+ident,version=slot['version'])
            attempt_id=claim['attempt_id'];directory=self.root/'attempts'/attempt_id;directory.mkdir(mode=0o700)
            write(directory/'claim.json',{'slot':definition,'claim':claim,'anchor_hash':digest(self.anchor)})
            version=self.store.mark(ident,attempt_id,self.owner,claim['version'],'RUNNING',{'claim_file':str(directory.relative_to(self.root)/'claim.json')})
            try:
                handler=self.generate if definition['slot_kind']=='generation' else self.execute
                result=handler(definition,attempt_id,dependencies,directory)
                if type(result) is not dict or result.get('status') not in {'COMPLETED','MODEL_FAILURE','PLAN_INVALID','INFRA_FAILURE','UNKNOWN','SENT_UNCONFIRMED','TIMEOUT','OOM','CANCELLED','TRANSFORM_NOT_APPLICABLE','NOT_AUTHORIZED','SERVICE_DRIFT'}:
                    raise ValueError('HANDLER_TERMINAL_STATUS')
            except Exception as exc:
                result={'status':'INFRA_FAILURE','failure_class':'INFRASTRUCTURE','exception_type':type(exc).__name__,'message':str(exc)}
            result={**result,'slot_id':ident,'attempt_id':attempt_id,'mode':self.mode,'source_hash':digest(self.identity)}
            if retry:result.update(reconciliation=retry['reconciliation'],reconciliation_evidence=retry['reconciliation_evidence'])
            result_hash=write(directory/'outcome.json',result)
            evidence={**{k:v for k,v in result.items() if k not in {'plan','records','proof'}},'result_file':(directory/'outcome.json').relative_to(self.root).as_posix(),'result_sha256':result_hash}
            status=result['status'];stored_status='UNKNOWN' if status in {'NOT_AUTHORIZED','SERVICE_DRIFT'} else status
            self.store.mark(ident,attempt_id,self.owner,version,stored_status,evidence)
            actual.append({'slot_id':ident,'attempt_id':attempt_id,'status':status})
            if status in {'MODEL_FAILURE','PLAN_INVALID'} and definition['slot_kind']=='generation':self.store.upstream_failure(ident,status)
            if status in PAUSE:
                paused.append({'slot_id':ident,'reason':status});break
        observations=self.store.observations(self.mode)
        snapshot={'revision':'FULL001_ATTEMPTS_1','mode':self.mode,'source_identity':self.identity,'anchor_hash':digest(self.anchor),'observations':observations}
        name='observations-'+str(uuid.uuid4())+'.json';write(self.root/name,snapshot)
        states=Counter(r['status'] for r in self.store.reconcile())
        complete=all(s not in {'NOT_RUN','CLAIMED','RUNNING','UNKNOWN','SENT_UNCONFIRMED'} for s in states)
        report={'phase':'CAMPAIGN_EXECUTION','status':'PAUSED_RECONCILIATION' if paused else 'TERMINAL' if complete else 'INCOMPLETE',
                'actual_attempts_this_invocation':actual,'states':dict(states),'paused':paused,
                'observation_file':name,'observation_sha256':sha(read(self.root/name)),'new_paid_authorization':False,'formal_ready':False}
        write(self.root/('invocation-'+str(uuid.uuid4())+'.json'),report);return report


class PreparedNativeExecutor:
    """Data and private verifier paths are supplied by the frozen task catalog."""
    def __init__(self,catalog,build,mode,*,host_scope=None,host_receipt=None,admission=None,semantic_services=None,cancel=None):
        self.catalog=catalog;self.build=Path(build);self.mode=mode;self.host_scope=host_scope
        self.host_receipt=host_receipt;self.admission=admission;self.semantic_services=semantic_services or {}
        self.cancel=cancel

    def __call__(self,slot,attempt_id,dependencies,directory):
        from rcwg_full.runtime.supervisor import execute
        from rcwg_full.verification.compare import check_output
        item=self.catalog[slot['task_id']];task=json.loads(read(item['task_path']))
        for name,hash_name in [('task_path','task_sha256'),('data_manifest','data_manifest_sha256'),('private_verifier','private_verifier_sha256')]:
            if sha(read(item[name]))!=item[hash_name]:raise ValueError('TASK_CATALOG_IDENTITY:'+name)
        generated=dependencies[slot['generation_slot_id']];plan=generated['plan']
        if digest(plan)!=generated['plan_hash']:raise ValueError('GENERATED_PLAN_HASH')
        original_plan_hash=digest(plan);frozen_binding=None;execution_profile=None;intervention=None
        if slot.get('experiment_id')=='E2':
            from .planning import rebind_frozen
            source={**slot,'condition':'C0','task_id':slot['task_id'].rsplit('-',1)[0]+'-C0'}
            frozen_binding=rebind_frozen(plan,source,slot)
        elif slot.get('experiment_id')=='E3' and slot.get('arm') in {'P','S'} or slot.get('experiment_id')=='E4':
            from .transforms import transform
            name='E3_'+slot['arm'] if slot['experiment_id']=='E3' else 'E4_'+slot['arm']
            intervention=transform(task,plan,name)
            if intervention['status']!='TRANSFORMED':return {'status':'TRANSFORM_NOT_APPLICABLE','intervention':intervention,'parent_plan_hash':original_plan_hash}
            plan=intervention['plan'];execution_profile=intervention['execution_profile'] or None
        elif slot.get('experiment_id')=='E5':
            from .diagnostics import bind_control,controls
            definition=next(d for d in controls() if d['control_plan_id']==slot['control_plan_id'])
            intervention=bind_control(definition,task,plan);plan=intervention['plan']
        private=json.loads(read(item['private_verifier']))
        def verify(actual,out):return check_output(actual,private['expected'],{'comparison':private['comparison']})
        driver=None
        if self.mode=='FORMAL':
            from rcwg_full.runtime.launch import approved_driver
            driver=approved_driver(self.host_scope,self.host_receipt,task,'r'+slot['slot_id'][:30],
                 source_hash=digest(source_hashes()),build_hash=sha(read(self.build/'BUILD.json')))
        def launch():return execute(task,plan,item['data_manifest'],build=self.build,output=directory/'native',mode=self.mode,
                 condition_id=slot['condition'],verify=verify,driver=driver,admission=self.admission,
                 semantic_replay=item.get('semantic_replay') if self.mode=='ENGINEERING_REPLAY' else None,
                 semantic_service=self.semantic_services.get('E1' if slot.get('experiment_id')=='E7' else 'E0') if self.mode=='FORMAL' else None,
                 frozen_binding=frozen_binding,execution_profile=execution_profile,cancel=self.cancel)
        if driver:
            from rcwg_native_n4.runner import watchdog,external_finalize
            maximum=self.host_scope['per_run_total_output_bytes']
            watched=watchdog(launch,time.monotonic()+task['resources']['wall_timeout_s']+15,
                 size_check=lambda:sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())>maximum)
            write(directory/'outer-watchdog.json',watched)
            if watched['exitcode']!=0:
                cleanup=external_finalize({'delegated_root':self.host_scope['delegated_root']},{'run_id':driver.ident},directory)
                return {'status':'INFRA_FAILURE','failure_class':'INFRASTRUCTURE','outer_watchdog':watched,'external_cleanup':cleanup,
                        'semantic':None,'budget':None,'exec_elapsed_ns':None,'worker_memory_peak_bytes':None}
            report=json.loads(read(directory/'native/report.json'))
        else:report=launch()
        measurements=report.get('measurements') or {};verified=report['verification']['status']
        bound=report.get('binding_validation',{}).get('status')=='EVIDENCE_BOUND'
        observed=measurements.get('status')=='COUNTERS_OBSERVED' and not report.get('cleanup_failures')
        budget=None
        if observed and report['terminal_status']=='COMPLETED' and report.get('exec_elapsed_ns') is not None and measurements.get('oom_kill_delta')==0:
            budget=measurements['worker_peak_ram_bytes']<=task['resources']['worker_memory_limit_bytes'] and report['exec_elapsed_ns']<=task['resources']['wall_timeout_s']*1e9
        result={'status':report['terminal_status'],'plan_hash':digest(plan),'data_hash':item['data_manifest_sha256'],
            'model_snapshot_hash':generated['model_snapshot_hash'],'profile_hash':digest(task['resources']),
            'semantic':True if verified=='PASS' else False if verified=='FAIL' else None,
            'budget':budget,'evidence_valid':bound,'comparison_context_hash':report.get('binding_validation',{}).get('comparison_context_hash'),
            'timing_valid':report['terminal_status']=='COMPLETED' and report.get('exec_elapsed_ns') is not None,
            'exec_elapsed_ns':report.get('exec_elapsed_ns'),'worker_memory_peak_bytes':measurements.get('worker_peak_ram_bytes'),
            'measurement':{'exec_elapsed_ns':'MEASURED' if report.get('exec_elapsed_ns') else 'UNKNOWN',
                           'worker_memory_peak_bytes':'MEASURED' if measurements.get('worker_peak_ram_bytes') is not None else 'UNKNOWN'},
            'supervisor_report_hash':sha(read(directory/'native/report.json')),
            'failure_class':'CONFIRMED_PLAN' if report['terminal_status'] in {'PLAN_INVALID','MODEL_FAILURE'} else 'INFRASTRUCTURE' if report['terminal_status']=='INFRA_FAILURE' else None}
        if frozen_binding is not None:result.update(c0_source_plan_hash=original_plan_hash,frozen_binding=frozen_binding)
        if intervention is not None:result['intervention']=intervention
        if slot.get('experiment_id')=='E5' and report['terminal_status']=='COMPLETED':
            from .diagnostics import inject_result,inject_journal
            if definition['arm']=='control' and definition['transform']=='result_corruption':
                actual=json.loads(read(directory/'native/worker/result.json'));changed,injection=inject_result(actual,definition)
                write(directory/'injected-result.json',changed);verification=verify(changed,directory)
                result.update(diagnostic_verification=verification,injection=injection)
            elif definition['arm']=='control' and definition['transform']=='journal_event_loss':
                changed,injection=inject_journal(read(directory/'native/worker/events.jsonl'),definition)
                write(directory/'injected-journal.jsonl',changed)
                from rcwg_full.verification.layers import check_complete_journal
                try:check_complete_journal(directory/'injected-journal.jsonl');verification={'status':'PASS'}
                except ValueError as exc:verification={'status':'FAIL','reason':str(exc)}
                result.update(diagnostic_verification=verification,injection=injection)
            else:result['diagnostic_verification']=report['verification']
            result['control_expectation_matched']=result['diagnostic_verification']['status']==definition['expected_verification']
        return result
