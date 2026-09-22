"""Physical requests: durable budget first, no resend of an uncertain request."""
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import json
import sqlite3
import uuid
import threading
from contextlib import contextmanager
from functools import wraps
from rcwg_full.evidence import canonical,digest,write,read,safe_path
from rcwg_full.campaign.sealing import validate_receipt
from rcwg_api.common import ApiError
from rcwg_api.vertex import parse_generation,parse_count
from .bindings import validate_binding
from .requests import assemble,parse_final


def serialized(method):
    @wraps(method)
    def run(self,*args,**kwargs):
        with self.lock:return method(self,*args,**kwargs)
    return run


class RequestIndex:
    """A request ID is permanently bound before any paid reservation or I/O."""
    def __init__(self,root):
        self.root=safe_path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=threading.RLock();self.active_operations=0;self.closing=False;self.closed=False
        self.db=sqlite3.connect(self.root/'request-index.sqlite3',timeout=30,isolation_level=None,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,status TEXT NOT NULL,result TEXT)')

    @serialized
    def begin(self,request_id,payload):
        if not isinstance(request_id,str) or str(uuid.UUID(request_id))!=request_id:raise ValueError('REQUEST_UUID')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT payload_hash,status,result FROM requests WHERE id=?',(request_id,)).fetchone()
            if row:
                if row[0]!=digest(payload):raise ValueError('REQUEST_ID_PAYLOAD_CONFLICT')
                self.db.execute('COMMIT')
                return False,json.loads(row[2]) if row[2] else {'status':'SENT_UNCONFIRMED','request_id':request_id,'reconciliation_required':True}
            self.db.execute('INSERT INTO requests VALUES(?,?,?,NULL)',(request_id,digest(payload),'PREPARED'))
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        directory=self.root/request_id;directory.mkdir(mode=0o700)
        write(directory/'request.json',payload)
        return True,None

    @serialized
    def record(self,request_id,status,result):
        write(self.root/request_id/(status.lower()+'.json'),result)
        self.db.execute('UPDATE requests SET status=?,result=? WHERE id=?',(status,canonical(result).decode(),request_id))

    @serialized
    def late_response(self,request_id,response):
        if not self.db.execute('SELECT 1 FROM requests WHERE id=?',(request_id,)).fetchone():raise ValueError('UNKNOWN_REQUEST')
        # Append only. Reconciliation is a separate decision; no terminal upgrade.
        name='late-'+str(uuid.uuid4())
        raw_hash=write(self.root/request_id/(name+'.raw'),response.body)
        write(self.root/request_id/(name+'.json'),{'request_id':request_id,'status':response.status,'raw_hash':raw_hash,'elapsed_ns':response.elapsed_ns,'observed_at':datetime.now(timezone.utc).isoformat(),'terminal_state_unchanged':True})

    @contextmanager
    def operation(self):
        # A cancelled worker can leave an HTTP call in flight. Keep its durable
        # index open until that call records the response; never resend it.
        with self.lock:
            if self.closing:raise RuntimeError('REQUEST_INDEX_CLOSING')
            self.active_operations+=1
        try:yield
        finally:
            with self.lock:
                self.active_operations-=1
                if self.closing and not self.active_operations and not self.closed:
                    self.db.close();self.closed=True

    def close(self):
        with self.lock:
            self.closing=True
            if not self.active_operations and not self.closed:self.db.close();self.closed=True


class ServiceClient:
    def __init__(self,binding,transport,budget,index,*,mode='ENGINEERING_REPLAY',scope_hash=None,receipt=None):
        if mode not in {'ENGINEERING_REPLAY','LIVE'}:raise ValueError('SERVICE_MODE')
        self.binding=validate_binding(binding,live=mode=='LIVE');self.transport=transport
        self.budget=budget;self.index=index;self.mode=mode;self.scope_hash=scope_hash;self.receipt=receipt
        if getattr(transport,'mode',None)!=mode:raise ValueError('TRANSPORT_MODE_MISMATCH')

    def call(self,request,kind,*,input_measurement=None):
        with self.index.operation():return self._call(request,kind,input_measurement=input_measurement)

    def _call(self,request,kind,*,input_measurement=None):
        if request['binding_hash']!=digest(self.binding) or request['body_hash']!=digest(request['body']):raise ValueError('REQUEST_BINDING')
        if kind not in {'G','E','COUNT'}:raise ValueError('REQUEST_KIND')
        payload={**request,'mode':self.mode,'kind':kind,'input_measurement':input_measurement}
        fresh,old=self.index.begin(request['request_id'],payload)
        if not fresh:return old
        rid=request['request_id']
        def finish(status,**fields):
            result={'request_id':rid,'status':status,'mode':self.mode,'binding_hash':digest(self.binding),
                    'remote_cpu_seconds':None,'remote_gpu_seconds':None,'remote_vram_bytes':None,
                    'remote_observability':'NOT_OBSERVABLE','actual_billing_usd':None,**fields}
            self.index.record(rid,status,result);return result
        try:
            if self.mode=='LIVE':
                validate_receipt(self.receipt,action='PAID_SERVICES',subject_hash=self.scope_hash,actor_role='Owner')
                if self.budget.manifest_hash!=self.scope_hash:raise PermissionError('BUDGET_SCOPE_BINDING')
                validate_binding(self.binding,live=True)
            if kind!='COUNT':
                m=input_measurement or {}
                if (m.get('body_hash')!=request['body_hash'] or m.get('tokenizer')!=self.binding['tokenizer'] or
                    type(m.get('tokens')) is not int or m['tokens']<0 or m.get('method')!=self.binding['count_method']):
                    raise PermissionError('EXACT_INPUT_TOKEN_MEASUREMENT_REQUIRED')
                if m['tokens']>request['max_input_tokens']:return finish('INPUT_LIMIT_EXCEEDED',sent=False)
            if self.mode=='LIVE':
                from .pricing import check_reservation
                check_reservation(self.binding,request,kind,input_measurement,self.budget)
                reservation=self.budget.reserve(rid,kind)
            else:reservation=None
        except (PermissionError,ApiError) as exc:
            return finish('NOT_AUTHORIZED',sent=False,reason=getattr(exc,'code',type(exc).__name__))
        self.index.record(rid,'SENDING',{'request_id':rid,'status':'SENT_UNCONFIRMED','reservation_microusd':reservation,'sent':None})
        try:
            response=self.transport.send(kind,canonical(request['body']),rid,reservation=reservation)
        except Exception as exc:
            result=finish('SENT_UNCONFIRMED',sent=None,reason=getattr(exc,'code',type(exc).__name__),reservation_microusd=reservation)
            if self.mode=='LIVE':self.budget.observe(rid,'SENT_UNCONFIRMED',digest(result))
            return result
        raw_hash=write(self.index.root/rid/'response.raw',response.body)
        try:
            if kind=='COUNT':
                parsed=parse_count(response);status='COMPLETED'
            else:
                prices=self.binding['price_snapshot']
                parsed=parse_generation(response,{'pricing':prices or {'input_usd_per_million':'0','output_usd_per_million':'0'}})
                if prices is None:parsed['usage']['cost_usd_list_price_upper_estimate']=None
                status='COMPLETED' if parsed['status']=='PROVIDER_TEXT_READY' else 'MODEL_FAILURE'
                if self.mode=='LIVE' and parsed['reported_model_version']!=self.binding['reported_revision']:status='SERVICE_DRIFT'
        except ApiError as exc:
            # A malformed provider envelope or HTTP error is not a bad WorkIR.
            # WorkIR parse failures are classified only after valid text delivery.
            parsed={'error':exc.code};status='INFRA_FAILURE'
        result=finish(status,sent=True,response=parsed,http_status=response.status,response_raw_hash=raw_hash,
                      service_latency_ns=response.elapsed_ns,reservation_microusd=reservation)
        if self.mode=='LIVE':self.budget.observe(rid,status,digest(result))
        return result

    def measure(self,request,*,local_counter=None):
        method=self.binding['count_method']
        if method=='LOCAL_TOKENIZER':
            if local_counter is None or getattr(local_counter,'identity',None)!=self.binding['tokenizer']:raise PermissionError('LOCAL_TOKENIZER_IDENTITY')
            count=local_counter(request['body'])
        elif method=='PROVIDER_COUNT':
            body={k:v for k,v in request['body'].items() if k in {'contents','systemInstruction'}}
            count_request={**request,'request_id':str(uuid.uuid4()),'body':body,'body_hash':digest(body)}
            result=self.call(count_request,'COUNT')
            if result['status']!='COMPLETED':return None,result
            count=result['response']['estimated_input_tokens']
        else:raise PermissionError('TOKEN_COUNT_METHOD_UNKNOWN')
        return {'method':method,'tokenizer':self.binding['tokenizer'],'tokens':count,'body_hash':request['body_hash']},None


def generate(task,slot,client,attempt_id,*,local_counter=None,guidance=None):
    protocol=slot['protocol'];stages=['physical'] if protocol=='P0' else ['logical','physical']
    if protocol not in {'P0','P1'}:raise ValueError('GENERATION_PROTOCOL')
    records=[];logical=None;plan=None;status='COMPLETED'
    if slot.get('generation_stage')=='GUIDED_PHYSICAL':
        from rcwg_full.campaign.transforms import public_guidance
        if protocol!='P1' or guidance!=public_guidance(task):raise ValueError('GUIDED_PHYSICAL_CONTRACT')
        stages=['physical']
        logical={'required_outputs':[canonical(guidance['output_contract']).decode()],
                 'hard_constraints':guidance['requirements'],'necessary_operations':['Implement the public task using the declared operator catalog.'],
                 'data_dependencies':[d['id'] for d in task['datasets']],
                 'information_requirements':[task['instruction']], 'permissible_alternatives':[],'uncertainty':[]}
    for stage in stages:
        if status!='COMPLETED':records.append({'stage':stage,'status':'NOT_RUN','request_id':None});continue
        request=assemble(task,client.binding,protocol=protocol,stage=stage,attempt_id=attempt_id,
                         request_id=str(uuid.uuid4()),trial_label=slot['trial_label'],logical=logical,guidance=guidance)
        try:
            measurement,failure=client.measure(request,local_counter=local_counter)
            response=failure or client.call(request,'G',input_measurement=measurement)
        except PermissionError as exc:response={'status':'NOT_AUTHORIZED','reason':str(exc),'sent':False}
        record={'stage':stage,'request_id':request['request_id'],'request_hash':digest(request),'response':response};records.append(record)
        if response['status']!='COMPLETED':
            status=response['status'];continue
        try:
            parsed=parse_final(response['response']['text'].encode('utf-8'),stage)
            record['parsed']=parsed
            if stage=='logical':logical=parsed['value']
            else:plan=parsed['value']
        except (ValueError,ApiError) as exc:
            status='MODEL_FAILURE';record['parse_failure']=getattr(exc,'code',type(exc).__name__)
    if status=='COMPLETED':
        from rcwg_full.compiler import FullCompiler
        proof=FullCompiler().compile(task,plan)
        if proof['status']!='IR_VALIDATED':status='PLAN_INVALID'
    else:proof=None
    return {'status':status,'generation_attempt_id':attempt_id,'protocol':protocol,'records':records,'plan':plan,
            'plan_hash':digest(plan) if plan else None,'proof':proof,'model_snapshot_hash':digest(client.binding),
            'physical_requests_sent':sum(r.get('response',{}).get('sent') is True for r in records),'formal_ready':False}


class FixedSemanticService:
    """The runner binds E0/E1. WorkIR never supplies a model or decoding setting."""
    def __init__(self,client,template,*,local_counter=None):
        if client.binding['slot'] not in {'E0','E1'} or digest(template)!=client.binding['template_hash']:raise ValueError('EXECUTOR_TEMPLATE_BINDING')
        self.client=client;self.template=template;self.local_counter=local_counter
        self.service_id=client.binding['slot'];self.mode=client.mode

    async def extract(self,request):
        return await asyncio.to_thread(self.extract_sync,request)

    def extract_sync(self,request):
        if request.get('service_id')!=self.service_id or set(request)!={'service_id','question','field_schema','contexts'}:raise ValueError('EXECUTOR_REQUEST_FIELDS')
        body={'systemInstruction':{'parts':[{'text':canonical(self.template).decode()}]},
              'contents':[{'role':'user','parts':[{'text':canonical(request).decode()}]}],
              'generationConfig':{'candidateCount':1,'maxOutputTokens':self.client.binding['max_output_tokens'],'responseMimeType':'application/json'}}
        for key,wire in [('temperature','temperature'),('top_k','topK'),('thinking','thinkingConfig')]:
            if self.client.binding['decoding'].get(key) is not None:body['generationConfig'][wire]=self.client.binding['decoding'][key]
        assembled={'request_id':str(uuid.uuid4()),'body':body,'body_hash':digest(body),'binding_hash':digest(self.client.binding),'max_input_tokens':12288,'kind':'E'}
        # HTTP waits run outside the event-loop and hold no CPU kernel slot.
        measurement,failure=self.client.measure(assembled,local_counter=self.local_counter)
        response=failure or self.client.call(assembled,'E',input_measurement=measurement)
        if response['status']!='COMPLETED':raise ValueError('SEMANTIC_'+response['status'])
        from rcwg_api.common import strict
        value=strict(response['response']['text'].encode('utf-8'))
        if type(value) is not list:raise ValueError('SEMANTIC_RESPONSE_LIST')
        return value
