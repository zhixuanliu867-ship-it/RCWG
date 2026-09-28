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
                 semantic_replay=None,semantic_service=None,admission=None,driver_factory=None,calibration=None,affinity=None):
        self.task=deepcopy(task);self.data_manifest=safe_path(data_manifest);self.private_verifier=safe_path(private_verifier)
        self.data_sha256=sha(read(self.data_manifest));self.verifier_sha256=sha(read(self.private_verifier))
        self.build=safe_path(build);self.directory=safe_path(directory);self.condition=condition;self.mode=mode
        self.replay=semantic_replay;self.service=semantic_service;self.admission=admission;self.driver_factory=driver_factory
        self.calibration=calibration;self.affinity=affinity;self.context=self._context()

    def _context(self):
        return context_for(self.task,DataCatalog(self.data_manifest),self.build,condition_id=self.condition,mode=self.mode,
            replay_sha256=sha(read(self.replay)) if self.replay else None,
            service_binding=self.service.client.binding if self.service else None,calibration=self.calibration,affinity=self.affinity)

    def __call__(self,plan,request):
        if (request['context_hash']!=self.context.comparison_context_hash or digest(plan)!=request['plan_hash'] or
            request['role'] not in {'REFERENCE_SCREEN','TIMING_CONFIRMATION'}):raise ValueError('REFERENCE_EXECUTION_BINDING')
        ident=str(uuid.UUID(request['attempt_id']))
        if (sha(read(self.data_manifest))!=self.data_sha256 or sha(read(self.private_verifier))!=self.verifier_sha256 or
            self._context().comparison_context_hash!=self.context.comparison_context_hash):raise ValueError('REFERENCE_SOURCE_CHANGED')
        from rcwg_full.verification.prepared import check_prepared
        def verify(actual,out):return check_prepared(actual,self.private_verifier)
        driver=self.driver_factory(request,self.task) if self.driver_factory else None
        report=execute(self.task,plan,self.data_manifest,build=self.build,output=self.directory/ident,
            mode=self.mode,condition_id=self.condition,verify=verify,driver=driver,admission=self.admission,
            semantic_replay=self.replay,semantic_service=self.service,record_role='REFERENCE',
            repeat_role='TIMING_CONFIRMATION' if request['role']=='TIMING_CONFIRMATION' else 'PRIMARY_REPEAT',
            generation_id=request['candidate_id'],repeat_id='r'+str(request['repeat']))
        bound=report.get('binding_validation',{});metrics=report.get('measurements',{});elapsed=report.get('exec_elapsed_ns')
        if bound.get('comparison_context_hash',request['context_hash'])!=request['context_hash']:raise ValueError('REFERENCE_MEASUREMENT_CONTEXT_CHANGED')
        from rcwg_full.runtime.measurement import terminal_budget
        decision=terminal_budget(report,self.task)
        verification=report['verification']['status']
        return {**request,**decision,'context_hash':bound.get('comparison_context_hash',request['context_hash']),
            'semantic':True if verification=='PASS' else False if verification=='FAIL' else None,
            'timing_valid':decision['timing_valid'] and bound.get('status')=='EVIDENCE_BOUND',
            'mode':self.mode,'reconciliation_required':report.get('service_reconciliation_required',False),
            'report_sha256':sha(read(self.directory/ident/'report.json')),'seal_sha256':sha(read(self.directory/ident/'seal.json')),
            'formal_ready':False}
