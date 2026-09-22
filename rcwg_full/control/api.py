"""Transaction-bound routes, metadata indexes and nine read-only projections."""
from copy import deepcopy
from dataclasses import dataclass
import json
import re
import time
import uuid
from rcwg_full.evidence import canonical,digest
from rcwg_full.campaign.store import CampaignStore,Conflict

KINDS={'campaign','model_snapshot','dataset_snapshot','task_instance','condition_profile','workflow',
       'run_attempt','node_instance','artifact','metric_summary','verification_record','audit_event','launch','campaign_slot'}
VIEWS=('Campaign','Queue','Workflow','Timeline','Node Inspector','Artifact Lifetime','Paired Compare','Metrics/Frontier','Audit/Export')
ROUTES=[('POST','/campaigns'),('POST','/campaigns/{id}/freeze'),('POST','/campaigns/{id}/runs'),
        ('GET','/runs/{id}'),('GET','/runs/{id}/events'),('POST','/runs/{id}/cancel'),
        ('GET','/workflows/{hash}'),('POST','/workflows/{hash}/fork'),('GET','/runs/{id}/artifacts'),
        ('POST','/campaigns/{id}/unseal'),('GET','/campaigns/{id}/export'),('GET','/campaigns/{id}/views'),('GET','/requests/{key}')]


@dataclass(frozen=True)
class Principal:
    actor_id:str
    role:str


class ControlAPI:
    def __init__(self,store,*,admission=None,audit_release=None):
        self.store=store;self.admission=admission;self.audit_release=audit_release

    def get(self,kind,ident):
        row=self.store.db.execute('SELECT * FROM metadata WHERE kind=? AND id=?',(kind,ident)).fetchone()
        if row is None:raise KeyError('NOT_FOUND')
        return {'id':ident,'version':row['version'],**json.loads(row['document'])}

    def put(self,kind,ident,document,*,version=None):
        if kind not in KINDS:raise ValueError('METADATA_KIND')
        if {'id','version'}&set(document):raise ValueError('RESERVED_METADATA_FIELDS')
        if version is not None and (type(version) is not int or version<0):raise ValueError('OPTIMISTIC_VERSION_TYPE')
        if kind in {'metric_summary','verification_record','node_instance','artifact','audit_event'}:
            document={'visibility':'PRIVATE',**document}
        if version is None:
            try:self.store.db.execute('INSERT INTO metadata VALUES(?,?,0,?)',(kind,ident,canonical(document).decode()))
            except __import__('sqlite3').IntegrityError as exc:raise Conflict('IDENTITY_EXISTS') from exc
            return 0
        cursor=self.store.db.execute('UPDATE metadata SET document=?,version=version+1 WHERE kind=? AND id=? AND version=?',
                                     (canonical(document).decode(),kind,ident,version))
        if cursor.rowcount!=1:raise Conflict('OPTIMISTIC_VERSION')
        return version+1

    def register(self,kind,ident,document):
        """Trusted controller indexing, never a provider-facing arbitrary route."""
        with self.store.transaction():return self.put(kind,ident,document)

    def rows(self,kind,campaign_id):
        result=[]
        for row in self.store.db.execute('SELECT * FROM metadata WHERE kind=? ORDER BY id',(kind,)):
            doc=json.loads(row['document'])
            if doc.get('campaign_id')==campaign_id:result.append({'id':row['id'],'version':row['version'],**doc})
        return result

    def attach_runner(self,campaign_id,runner):
        """Trusted deployment wiring; no caller-supplied handler or executable."""
        campaign=self.get('campaign',campaign_id)
        if (runner.store.path!=self.store.path or runner.anchor['manifest_hash']!=campaign['manifest_hash'] or
            runner.anchor['spec_hash']!=campaign['spec_hash'] or runner.mode!=campaign['mode']):raise ValueError('CONTROL_RUNNER_BINDING')
        with self.store.transaction():
            for slot_id in runner.slots:
                document={'campaign_id':campaign_id,'runner_anchor_hash':digest(runner.anchor)}
                try:old=self.get('campaign_slot',slot_id)
                except KeyError:self.put('campaign_slot',slot_id,document)
                else:
                    if {k:v for k,v in old.items() if k not in {'id','version'}}!=document:raise Conflict('CONTROL_SLOT_ALREADY_BOUND')

    def dispatch_one(self,campaign_id,runner):
        """Outbox claims never expire into duplicate execution; crash needs reconcile."""
        if runner.store.path!=self.store.path:raise ValueError('CONTROL_RUNNER_STORE')
        with self.store.transaction():
            queued=self.rows('launch',campaign_id);pending=[r for r in queued if r['status']=='PENDING']
            if not pending:return {'status':'NO_NEW_ACTION','reconcile_required':[r['id'] for r in queued if r['status']=='CLAIMED']}
            from rcwg_full.campaign.runner import ordered_slots
            order={row['slot_id']:i for i,row in enumerate(ordered_slots(list(runner.slots.values())))}
            ready=[]
            for candidate in sorted(pending,key=lambda r:order.get(r['id'],len(order))):
                slot=self.store.slot(candidate['id']);run=self.get('run_attempt',candidate['run_id'])
                if run['cancel_requested'] or slot['status']!='NOT_RUN':ready.append(candidate);continue
                if all(dependency in runner.external_dependencies or self.store.slot(dependency)['status'] in
                       {'COMPLETED','MODEL_FAILURE','PLAN_INVALID'} for dependency in slot['definition'].get('expected_dependencies',[])):
                    ready.append(candidate)
            if not ready:return {'status':'WAITING_DEPENDENCIES','new_actions':0}
            launch=ready[0];binding=self.get('campaign_slot',launch['id'])
            if binding['runner_anchor_hash']!=digest(runner.anchor):raise ValueError('CONTROL_RUNNER_ANCHOR')
            self.put('launch',launch['id'],{k:v for k,v in {**launch,'status':'CLAIMED'}.items() if k not in {'id','version'}},version=launch['version'])
            run=self.get('run_attempt',launch['run_id'])
            self.put('run_attempt',run['id'],{k:v for k,v in {**run,'status':'CLAIMED'}.items() if k not in {'id','version'}},version=run['version'])
        cancelled=lambda:self.get('run_attempt',run['id'])['cancel_requested']
        slot=self.store.slot(launch['id'])
        if cancelled() and slot['status']=='NOT_RUN':self.store.cancel_pending(launch['id'],slot['version'])
        if hasattr(runner.execute,'cancel'):runner.execute.cancel=cancelled
        outcome=runner.run(cancel=cancelled,selected_slots=[launch['id']]);slot=self.store.slot(launch['id'])
        with self.store.transaction():
            current=self.get('run_attempt',run['id']);terminal=slot['status']
            if terminal=='NOT_RUN' and current['cancel_requested']:terminal='CANCELLED'
            self.put('run_attempt',run['id'],{k:v for k,v in {**current,'status':terminal,'attempt_id':slot['active_attempt'],
                'outcome_manifest':outcome['observation_file']}.items() if k not in {'id','version'}},version=current['version'])
            record=self.get('launch',launch['id'])
            self.put('launch',record['id'],{k:v for k,v in {**record,'status':'RECONCILE_REQUIRED' if outcome['paused'] and terminal!='CANCELLED' else 'DISPATCHED'}.items() if k not in {'id','version'}},version=record['version'])
            self.store._audit('outbox_dispatch',{'run_id':run['id'],'slot_id':launch['id'],'attempt_id':slot['active_attempt'],'status':terminal,'outcome_hash':digest(outcome)})
        return {'run':self.get('run_attempt',run['id']),'runner_outcome':outcome}

    @staticmethod
    def closed(body,required,optional=()):
        if type(body) is not dict or not set(required)<=set(body) or set(body)-set(required)-set(optional):raise ValueError('REQUEST_FIELDS')

    @staticmethod
    def role(principal,roles):
        if principal.role not in roles:raise PermissionError('ROLE_DENIED')

    def visible(self,document,principal):
        if document.get('visibility','PUBLIC')=='PUBLIC':return deepcopy(document)
        campaign=self.get('campaign',document['campaign_id'])
        if principal.role=='Auditor' and campaign.get('audit_released') is True:return deepcopy(document)
        # An opaque ID is safe; raw verification, metrics and private payloads
        # remain absent rather than recursively guessing which keys are gold.
        return {k:document[k] for k in ['id','kind','visibility','campaign_id'] if k in document}|{'status':'SEALED_PRIVATE'}

    def handle(self,method,path,body,*,principal,idempotency_key=None):
        try:
            if not isinstance(principal,Principal) or not principal.actor_id or principal.role not in {'Owner','Operator','Auditor','Viewer'}:
                raise PermissionError('AUTHENTICATED_PRINCIPAL_REQUIRED')
            if type(path) is not str or '?' in path or '%' in path or not path.startswith('/'):raise ValueError('ROUTE_PATH')
            if method=='GET':return 200,self._route(method,path,{},principal)
            if method!='POST':return 405,{'status':'METHOD_NOT_ALLOWED'}
            if not isinstance(idempotency_key,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',idempotency_key):raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
            payload={'method':method,'path':path,'body':body,'actor_id':principal.actor_id,'role':principal.role}
            request_hash=digest(payload);key='control:'+principal.actor_id+':'+idempotency_key
            with self.store.transaction():
                row=self.store.db.execute('SELECT payload_hash,response FROM requests WHERE key=?',(key,)).fetchone()
                if row:
                    if row['payload_hash']!=request_hash:raise Conflict('IDEMPOTENCY_PAYLOAD_CONFLICT')
                    return 200,json.loads(row['response'])
                result=self._route(method,path,body,principal)
                self.store.db.execute('INSERT INTO requests VALUES(?,?,?)',(key,request_hash,canonical(result).decode()))
                self.store._audit('control',{'actor_id':principal.actor_id,'role':principal.role,'method':method,'path':path,'request_hash':request_hash,'result_hash':digest(result)})
            return 200,result
        except PermissionError as exc:return 403,{'status':'DENIED','code':str(exc)}
        except Conflict as exc:return 409,{'status':'CONFLICT','code':str(exc)}
        except KeyError:return 404,{'status':'NOT_FOUND'}
        except (ValueError,TypeError) as exc:return 400,{'status':'INVALID','code':str(exc)}

    def _route(self,method,path,body,principal):
        parts=path.strip('/').split('/')
        if method=='GET' and len(parts)==2 and parts[0]=='requests':
            row=self.store.db.execute('SELECT response FROM requests WHERE key=?',('control:'+principal.actor_id+':'+parts[1],)).fetchone()
            if row is None:raise KeyError('REQUEST_UNKNOWN')
            return {'status':'REQUEST_COMMITTED','response':json.loads(row['response']),'replayed':True,'new_actions':0}
        if method=='POST' and parts==['campaigns']:
            self.role(principal,{'Owner','Operator'});self.closed(body,{'manifest_hash','spec_hash','mode'}, {'label'})
            if body['mode'] not in {'FORMAL','ENGINEERING_NATIVE','ENGINEERING_REPLAY'}:raise ValueError('CAMPAIGN_MODE')
            if any(not isinstance(body[k],str) or not re.fullmatch('[0-9a-f]{64}',body[k]) for k in ['manifest_hash','spec_hash']):raise ValueError('CAMPAIGN_HASH')
            ident=str(uuid.uuid4());doc={**body,'status':'DRAFT','audit_released':False,'owner':principal.actor_id}
            self.put('campaign',ident,doc);return self.get('campaign',ident)
        if len(parts)==3 and parts[0]=='campaigns':
            ident,action=parts[1:];campaign=self.get('campaign',ident)
            if method=='GET' and action=='views':return self.views(ident,principal)
            if method=='GET' and action=='export':
                return {'campaign':campaign,'views':self.views(ident,principal),'manifest_hash':campaign['manifest_hash'],
                        'formal_ready':False,'export_role':principal.role,'private_released':principal.role=='Auditor' and campaign['audit_released']}
            if method=='POST' and action=='freeze':
                self.role(principal,{'Owner'});self.closed(body,{'version','freeze_hash'})
                if campaign['status']!='DRAFT':raise Conflict('FROZEN_IMMUTABLE')
                if not isinstance(body['freeze_hash'],str) or not re.fullmatch('[0-9a-f]{64}',body['freeze_hash']):raise ValueError('FREEZE_HASH')
                doc={k:v for k,v in campaign.items() if k not in {'id','version'}}
                doc.update(status='FROZEN',freeze_hash=body['freeze_hash'])
                self.put('campaign',ident,doc,version=body['version']);return self.get('campaign',ident)
            if method=='POST' and action=='runs':
                self.role(principal,{'Owner','Operator'});self.closed(body,{'version','slot_id','workflow_hash'})
                if campaign['version']!=body['version']:raise Conflict('OPTIMISTIC_VERSION')
                if campaign['status']!='FROZEN':raise PermissionError('CAMPAIGN_NOT_FROZEN')
                workflow=self.get('workflow',body['workflow_hash'])
                if workflow['campaign_id']!=ident or workflow.get('mode')=='MANUAL_DEBUG':raise PermissionError('WORKFLOW_CAMPAIGN_BINDING')
                if campaign['mode']=='FORMAL':
                    if self.admission is None or self.admission(campaign).get('status')!='ADMITTED':raise PermissionError('FORMAL_ADMISSION_REQUIRED')
                slot=self.store.slot(body['slot_id'])
                associated=slot['definition'].get('campaign_id')
                if associated is None:associated=self.get('campaign_slot',body['slot_id'])['campaign_id']
                if associated!=ident:raise PermissionError('SLOT_CAMPAIGN_BINDING')
                existing=self.store.db.execute("SELECT id FROM metadata WHERE kind='launch' AND id=?",(body['slot_id'],)).fetchone()
                if existing:raise Conflict('SLOT_ALREADY_QUEUED')
                run_id=str(uuid.uuid4());doc={'campaign_id':ident,'slot_id':body['slot_id'],'workflow_hash':body['workflow_hash'],'status':'QUEUED','cancel_requested':False,'mode':campaign['mode']}
                self.put('run_attempt',run_id,doc);self.put('launch',body['slot_id'],{'campaign_id':ident,'run_id':run_id,'status':'PENDING'})
                return self.get('run_attempt',run_id)
            if method=='POST' and action=='unseal':
                self.role(principal,{'Auditor'});self.closed(body,{'version','receipt'})
                if campaign['version']!=body['version']:raise Conflict('OPTIMISTIC_VERSION')
                if campaign['status']!='SEALED' or campaign.get('core_complete') is not True:raise PermissionError('CORE_NOT_SEALED')
                if body['receipt'].get('actor_id')!=principal.actor_id or body['receipt'].get('actor_role')!=principal.role:raise PermissionError('RECEIPT_PRINCIPAL_MISMATCH')
                if self.audit_release is None:raise PermissionError('SEALED_PACKAGE_VERIFIER_REQUIRED')
                release=self.audit_release(campaign,body['receipt'])
                if release.get('sealed_manifest_hash')!=campaign.get('sealed_manifest_hash'):raise PermissionError('RELEASE_BINDING')
                doc={k:v for k,v in campaign.items() if k not in {'id','version'}};doc.update(audit_released=True,audit_release_hash=digest(release))
                self.put('campaign',ident,doc,version=body['version']);return self.get('campaign',ident)
        if len(parts) in {2,3} and parts[0]=='runs':
            run=self.get('run_attempt',parts[1]);action=parts[2] if len(parts)==3 else None
            if method=='GET' and action is None:return self.visible(run,principal)
            if method=='GET' and action in {'events','artifacts'}:
                kind='node_instance' if action=='events' else 'artifact'
                rows=[self.visible(r,principal) for r in self.rows(kind,run['campaign_id']) if r.get('run_id')==parts[1]]
                return {'run_id':parts[1],'items':rows}
            if method=='POST' and action=='cancel':
                self.role(principal,{'Owner','Operator'});self.closed(body,{'version'})
                if run['status'] not in {'QUEUED','CLAIMED','RUNNING','SENT_UNCONFIRMED'}:raise Conflict('TERMINAL_IMMUTABLE')
                doc={k:v for k,v in run.items() if k not in {'id','version'}};doc['cancel_requested']=True
                self.put('run_attempt',parts[1],doc,version=body['version']);return self.get('run_attempt',parts[1])
        if len(parts) in {2,3} and parts[0]=='workflows':
            workflow=self.get('workflow',parts[1])
            if method=='GET' and len(parts)==2:return self.visible(workflow,principal)
            if method=='POST' and len(parts)==3 and parts[2]=='fork':
                self.role(principal,{'Owner','Operator'});self.closed(body,{'version','plan'})
                if workflow['version']!=body['version']:raise Conflict('OPTIMISTIC_VERSION')
                ident=digest({'parent':parts[1],'plan':body['plan'],'fork_nonce':str(uuid.uuid4())})
                self.put('workflow',ident,{'parent':parts[1],'plan':body['plan'],'mode':'MANUAL_DEBUG','ledger_role':'MANUAL_DEBUG','campaign_id':None,'visibility':'PUBLIC'})
                return self.get('workflow',ident)
        raise KeyError('ROUTE_NOT_FOUND')

    def views(self,campaign_id,principal):
        campaign=self.get('campaign',campaign_id)
        kinds={k:[self.visible(r,principal) for r in self.rows(k,campaign_id)] for k in KINDS if k not in {'campaign','launch'}}
        return {'schema_version':'FULL001_NINE_VIEWS_1','campaign_id':campaign_id,'manifest_hash':campaign['manifest_hash'],
          'views':{'Campaign':[campaign],'Queue':kinds['run_attempt'],'Workflow':kinds['workflow'],
          'Timeline':kinds['node_instance'],'Node Inspector':kinds['node_instance'],
          'Artifact Lifetime':kinds['artifact'],'Paired Compare':[r for r in kinds['metric_summary'] if r.get('comparison')],
          'Metrics/Frontier':kinds['metric_summary'],'Audit/Export':kinds['audit_event']},'formal_ready':False}


def offline_html(view_document):
    import html
    if set(view_document['views'])!=set(VIEWS):raise ValueError('NINE_VIEWS_REQUIRED')
    sections=''.join('<section><h2>'+html.escape(name)+'</h2><pre>'+html.escape(json.dumps(view_document['views'][name],ensure_ascii=False,indent=2))+'</pre></section>' for name in VIEWS)
    return ('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>RCWG control views</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;background:#f8fafc;color:#172554}section{background:white;border:1px solid #cbd5e1;border-radius:8px;padding:20px;margin:16px 0}pre{overflow:auto;white-space:pre-wrap;word-break:break-word}h1{font-size:30px}</style><h1>RCWG · 九类只读视图</h1><p>离线快照；正式门禁状态以冻结与准入证据为准。</p>'+sections+'</html>').encode('utf-8')
