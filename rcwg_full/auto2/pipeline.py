"""Resumable two-phase controller using actual adapters and fixed denominators."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import json,uuid
from rcwg_full.evidence import read,write,sha,digest,source_hashes
from rcwg_full.services.client import RequestIndex,generate,FixedSemanticService
from rcwg_full.auto2.control import TaskState,advance_to_live,preparation_gate
from rcwg_full.auto2.services import ExistingWindowsIdentity,DelegatedVertexTransport,DelegatedClient,ScopeBudget


def load(path):return json.loads(read(path))


class Pipeline:
    def __init__(self,root,policy,executor):
        self.root=Path(root).absolute();self.policy=policy;self.config=load(self.root/'RUN_CONFIG.json');self.executor=executor
        self.state=TaskState(self.root/'state',policy,load(self.root/'ROOT_DELEGATION_RECORD.json'))
        self.models=load(self.root/'state/MODEL_LOCK.json');self.plan=load(self.root/'PREREGISTRATION.json')
        self.index=RequestIndex(self.root/'private/requests');self.identity=load(self.root/'IDENTITY.json')
        self.credentials=None;self.transport=None;self.available=[]

    def current_identity(self):
        identity=dict(self.identity)
        identity.update(source=digest(source_hashes()),models=digest(load(self.root/'state/MODEL_LOCK.json')),
                        data=digest(load(self.root/'DATA_LOCK.json')),manifest=digest(load(self.root/'PREREGISTRATION.json')))
        live=self.executor.identity()
        for key in ['boot','host','build','dependencies']:identity[key]=live[key]
        return identity

    def scope(self,stage,limits,ceiling,*,scope_key=None):
        suffix='-'+digest(scope_key) if scope_key is not None else ''
        file=self.root/(stage+suffix+'-'+digest(self.current_identity())+'-scope.json')
        if file.exists():
            scope=load(file)
            self.state.validate_scope(scope,self.current_identity());return scope
        scope=self.state.derive_scope(stage=stage,identity=self.current_identity(),limits=limits,ceiling_microusd=ceiling,
            expires_at=(datetime.now(timezone.utc)+timedelta(hours=20)).isoformat())
        write(file,scope);return scope

    def client(self,slot,scope):
        if self.credentials is None:
            self.credentials=ExistingWindowsIdentity(load(self.config['existing_identity_reference']))
            self.transport=self.credentials.existing_transport()
        binding=next(b for b in self.models['bindings'] if b['slot']==slot)
        budget=ScopeBudget(self.state,scope,self.current_identity,self.plan['reservation_microusd'][slot])
        return DelegatedClient(binding,DelegatedVertexTransport(binding,self.transport),budget,self.index)

    def request_id(self,name):return str(uuid.uuid5(uuid.NAMESPACE_URL,self.state.summary()['root_hash']+':'+name))

    def capability(self,slot,scope):
        client=self.client(slot,scope);binding=client.binding
        body={'contents':[{'role':'user','parts':[{'text':'Return exactly the JSON object {"ready":true}. No tools or external data.'}]}],
              'generationConfig':{'candidateCount':1,'maxOutputTokens':128,'responseMimeType':'application/json'}}
        for key,wire in [('temperature','temperature'),('thinking','thinkingConfig')]:
            if binding['decoding'].get(key) is not None:body['generationConfig'][wire]=binding['decoding'][key]
        request={'request_id':self.request_id('capability:'+slot),'body':body,'body_hash':digest(body),
                 'binding_hash':digest(binding),'max_input_tokens':12288,'max_output_tokens':128}
        measurement,failure=client.measure(request)
        return failure or client.call(request,'G',input_measurement=measurement)

    def save_once(self,name,value):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():return load(path)
        write(path,value);return value

    def require_resolved_facility(self,record,job_id):
        status=record.get('status')
        if status in {'INFRA_FAILURE','SENT_UNCONFIRMED','UNKNOWN','SERVICE_DRIFT','NOT_AUTHORIZED'}:
            self.state.transition('PAUSED_EXTERNAL',{'job_id':job_id,'status':status,
                'record_sha256':digest(record),'reason':'ACTUAL_FACILITY_REQUIRES_RECONCILIATION',
                'provider_retry_permitted':False})
            raise PermissionError('ACTUAL_FACILITY_REQUIRES_RECONCILIATION:'+job_id+':'+str(status))

    def generation(self,job,scope):
        file=self.root/'private/generations'/(job['id']+'.json')
        if file.exists():return load(file)
        raw=read(self.root/job['task_file'])
        if sha(raw)!=job['task_file_sha256']:raise PermissionError('FROZEN_PUBLIC_TASK_CHANGED')
        from rcwg_full.auto2.data import public_export
        task=public_export({'task':json.loads(raw)})['task'];client=self.client(job['generator'],scope)
        result=generate(task,job,client,job['id'],request_id_factory=lambda stage:self.request_id(job['id']+':'+stage))
        return self.save_once('private/generations/'+job['id']+'.json',result)

    def execution(self,job,plan,scope,*,reference=False):
        file=self.root/'private/executions'/(job['id']+'.json')
        if file.exists():return load(file)
        if plan is None:return self.save_once('private/executions/'+job['id']+'.json',{'status':'NOT_RUN','reason':'GENERATION_NOT_VALID','job':job})
        service=None
        if job.get('executor'):
            if scope['stage']=='B_DEVELOPMENT':
                bound=self.plan['development_semantic_requests_per_execution']
                if type(bound) is not int or not 1<=bound<=8:raise PermissionError('SEMANTIC_JOB_FINITE_BOUND')
                rates=self.plan['reservation_microusd'][job['executor']]
                scope=self.scope('B_DEVELOPMENT',{'E':bound,'COUNT':bound},bound*(rates['E']+rates['COUNT']),scope_key=job['id'])
            counter=[0]
            def rid(request):
                counter[0]+=1
                return self.request_id(job['id']+':E:'+str(counter[0])+':'+digest(request))
            service=FixedSemanticService(self.client(job['executor'],scope),self.models['executor_template'],request_id_factory=rid)
        host_request=None
        if scope['stage'] in {'B_REFERENCE','B_FORMAL'}:
            host_request=self.request_id('host:'+job['id'])
            self.state.reserve(scope,host_request,'HOST',0,self.current_identity())
        result=self.executor.execute(job,plan,service,reference=reference)
        if host_request:self.state.observe(host_request,result['status'],{'result_sha256':digest(result)})
        return self.save_once('private/executions/'+job['id']+'.json',result)

    def run(self):
        initial=self.scope('B_INITIAL',{'G':24,'E':4,'COUNT':28},15_000_000)
        pipeline=self
        class FirstActualRequest:
            mode='LIVE'
            def __call__(self):return pipeline.capability('G0',initial)
        # Revalidation is always performed, including on a resumed process.
        evidence=load(self.root/'PREPARATION_EVIDENCE.json')
        self.save_once('preparation-gate.json',preparation_gate(evidence,self.current_identity(),self.config['measurement_profile']))
        if self.state.summary()['state']=='PREPARING':
            first=advance_to_live(self.state,initial,evidence,self.current_identity(),self.config['measurement_profile'],FirstActualRequest())
        else:
            preparation_gate(evidence,self.current_identity(),self.config['measurement_profile'])
            first=self.capability('G0',initial)
        capabilities={'G0':first}
        self.save_once('private/capabilities/G0.json',first)
        if first.get('status') in {'SENT_UNCONFIRMED','UNKNOWN','SERVICE_DRIFT','NOT_AUTHORIZED'}:
            self.require_resolved_facility(first,'capability:G0')
        for slot in ['G1','G2','G3','G4','G5']:
            record=self.capability(slot,initial)
            capabilities[slot]=record
            self.save_once('private/capabilities/'+slot+'.json',record)
            if record.get('status') in {'SENT_UNCONFIRMED','UNKNOWN','SERVICE_DRIFT','NOT_AUTHORIZED'}:
                self.require_resolved_facility(record,'capability:'+slot)
        self.save_once('CAPABILITIES.json',capabilities)
        self.available=[s for s,r in capabilities.items() if r['status'] in {'COMPLETED','MODEL_FAILURE'} and r.get('http_status')==200]
        for slot,record in capabilities.items():
            # A resolved model-specific HTTP refusal may reduce coverage. An
            # uncertain send or local authorization failure cannot be retried.
            if record.get('status') in {'SENT_UNCONFIRMED','UNKNOWN','SERVICE_DRIFT','NOT_AUTHORIZED'}:
                self.require_resolved_facility(record,'capability:'+slot)
        if not self.available:
            self.require_resolved_facility({'status':'INFRA_FAILURE','reason':'NO_AVAILABLE_GENERATOR'},'capabilities')
        for job in self.plan['initial_generations']:
            if job['generator'] in self.available:
                generated=self.generation(job,initial)
                self.require_resolved_facility(generated,job['id'])
                for execution in job['executions']:
                    outcome=self.execution(execution,generated['plan'] if generated['status']=='COMPLETED' else None,initial)
                    self.require_resolved_facility(outcome,execution['id'])
            else:self.save_once('private/generations/'+job['id']+'.json',{'status':'NOT_RUN','reason':'MODEL_FACILITY_UNAVAILABLE','plan':None})
        for job in self.plan['initial_semantic_references']:
            outcome=self.execution(job,load(self.root/job['reference_plan_file']),initial,reference=True)
            self.require_resolved_facility(outcome,job['id'])
        # Selection was frozen from bounds before seeing any model outcomes.
        for block in self.plan['development_blocks']:
            block_file=self.root/'private/blocks'/(block['id']+'.json')
            if block_file.exists():continue
            if not self.state.affordable(block['reserved_upper_microusd']):
                self.state.transition('PAUSED_BUDGET',{'next_complete_block':block['id'],'upper_microusd':block['reserved_upper_microusd']});break
            scope=self.scope('B_DEVELOPMENT',self.plan['development_limits'],self.plan['development_ceiling_microusd'])
            for job in block['generations']:
                if job['generator'] not in self.available:
                    self.save_once('private/generations/'+job['id']+'.json',{'status':'NOT_RUN','reason':'MODEL_FACILITY_UNAVAILABLE','plan':None});continue
                generated=self.generation(job,scope)
                self.require_resolved_facility(generated,job['id'])
                for execution in job['executions']:
                    outcome=self.execution(execution,generated['plan'] if generated['status']=='COMPLETED' else None,scope)
                    self.require_resolved_facility(outcome,execution['id'])
            self.save_once('private/blocks/'+block['id']+'.json',{'status':'ATTEMPTS_RECORDED','block_id':block['id']})
        from .formal import continue_references_and_formal
        self.save_once('FORMAL_GATE_RESULT.json',continue_references_and_formal(self))
        final=self.state.summary()
        if final['state']=='LIVE_RUNNING':self.state.transition('RESULTS_SEALED',{'available_generators':self.available,'formal':load(self.root/'FORMAL_GATE_RESULT.json')})
        return self.state.summary()
