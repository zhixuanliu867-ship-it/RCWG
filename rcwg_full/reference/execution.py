"""Reference candidates use the same native supervisor and private verifier."""
from copy import deepcopy
import json
import uuid
from rcwg_full.evidence import read,sha,digest,safe_path
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.runtime.supervisor import context_for,execute
from rcwg_full.verification.compare import check_output


class NativeReferenceExecutor:
    def __init__(self,task,data_manifest,private_verifier,build,directory,*,condition,mode='ENGINEERING_NATIVE',
                 semantic_replay=None,semantic_service=None,admission=None,driver_factory=None):
        self.task=deepcopy(task);self.data_manifest=safe_path(data_manifest);self.private_verifier=safe_path(private_verifier)
        self.data_sha256=sha(read(self.data_manifest));self.verifier_sha256=sha(read(self.private_verifier))
        self.build=safe_path(build);self.directory=safe_path(directory);self.condition=condition;self.mode=mode
        self.replay=semantic_replay;self.service=semantic_service;self.admission=admission;self.driver_factory=driver_factory
        self.context=self._context()

    def _context(self):
        return context_for(self.task,DataCatalog(self.data_manifest),self.build,condition_id=self.condition,mode=self.mode,
            replay_sha256=sha(read(self.replay)) if self.replay else None,
            service_binding=self.service.client.binding if self.service else None)

    def __call__(self,plan,request):
        if (request['context_hash']!=self.context.comparison_context_hash or digest(plan)!=request['plan_hash'] or
            request['role'] not in {'REFERENCE_SCREEN','TIMING_CONFIRMATION'}):raise ValueError('REFERENCE_EXECUTION_BINDING')
        ident=str(uuid.UUID(request['attempt_id']))
        if (sha(read(self.data_manifest))!=self.data_sha256 or sha(read(self.private_verifier))!=self.verifier_sha256 or
            self._context().comparison_context_hash!=self.context.comparison_context_hash):raise ValueError('REFERENCE_SOURCE_CHANGED')
        private=json.loads(read(self.private_verifier))
        def verify(actual,out):return check_output(actual,private['expected'],{'comparison':private['comparison']})
        driver=self.driver_factory(request,self.task) if self.driver_factory else None
        report=execute(self.task,plan,self.data_manifest,build=self.build,output=self.directory/ident,
            mode=self.mode,condition_id=self.condition,verify=verify,driver=driver,admission=self.admission,
            semantic_replay=self.replay,semantic_service=self.service,record_role='REFERENCE',
            repeat_role='TIMING_CONFIRMATION' if request['role']=='TIMING_CONFIRMATION' else 'PRIMARY_REPEAT',
            generation_id=request['candidate_id'],repeat_id='r'+str(request['repeat']))
        bound=report.get('binding_validation',{});metrics=report.get('measurements',{});elapsed=report.get('exec_elapsed_ns')
        observed=metrics.get('status')=='COUNTERS_OBSERVED' and not report.get('cleanup_failures')
        budget=None
        if observed and report['terminal_status']=='COMPLETED' and elapsed is not None and metrics.get('oom_kill_delta')==0:
            budget=(metrics['worker_peak_ram_bytes']<=self.task['resources']['worker_memory_limit_bytes'] and
                    elapsed<=self.task['resources']['wall_timeout_s']*1e9)
        verification=report['verification']['status']
        return {**request,'status':report['terminal_status'],'context_hash':bound.get('comparison_context_hash',request['context_hash']),
            'semantic':True if verification=='PASS' else False if verification=='FAIL' else None,'budget':budget,
            'timing_valid':report['terminal_status']=='COMPLETED' and elapsed is not None and bound.get('status')=='EVIDENCE_BOUND',
            'exec_elapsed_ns':elapsed,'mode':self.mode,'reconciliation_required':report.get('service_reconciliation_required',False),
            'report_sha256':sha(read(self.directory/ident/'report.json')),'seal_sha256':sha(read(self.directory/ident/'seal.json')),
            'formal_ready':False}
