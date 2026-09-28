"""Independent process watch for one physical call, including token and seal.

The parent never sends. It reads the durable result after child exit. A killed
or crashed child is fenced and persisted unresolved; restart cannot resend.
"""
import json,multiprocessing,time
from pathlib import Path
from rcwg_full.evidence import digest,write
from rcwg_full.services.client import RequestIndex
from rcwg_full.services.timeout3 import PROFILE,validate
from .control import TaskState
from .dispatch import DispatchGate
from .services import DelegatedClient,DelegatedVertexTransport,ScopeBudget
from .next_live import NextLiveClient,_lookup_result

def run_process(target,args,seconds):
    start=time.monotonic()
    process=multiprocessing.get_context('spawn').Process(target=target,args=args)
    process.start();process.join(max(0,seconds-(time.monotonic()-start)))
    timed_out=process.is_alive()
    if timed_out:
        process.terminate();process.join(5)
        if process.is_alive():process.kill();process.join(5)
        if process.is_alive():raise RuntimeError('WATCHDOG_CHILD_STILL_ALIVE')
    result={'revision':'G_PROCESS_WATCHDOG_1','pid':process.pid,'exitcode':process.exitcode,
            'timed_out':timed_out,'deadline_seconds':seconds,'elapsed_seconds':time.monotonic()-start,
            'child_stopped':True,'provider_active_count':None}
    process.close();return result

def _call(root,policy,authority,scope,amounts,identity,index_root,credentials,binding,request,kind,measurement):
    state=TaskState(Path(root),policy,authority);index=RequestIndex(Path(index_root))
    try:
        existing=credentials.existing_transport(timeout_profile=PROFILE)
        client=DelegatedClient(binding,DelegatedVertexTransport(binding,existing),
            ScopeBudget(state,scope,lambda:identity,amounts),index)
        client.call(request,kind,input_measurement=measurement)
    finally:
        write(index.root/('auth-'+request['request_id']+'.json'),{'audit':credentials.audit,'token_persisted':False})
        index.close()

def reconcile_exit(state,index,rid,proof):
    """Only the stopped child may be reconciled, with no network or retry."""
    if proof.get('child_stopped') is not True:raise PermissionError('WATCHDOG_STOP_PROOF_REQUIRED')
    with DispatchGate(state).locked() as gate,state.db() as db:
        db.execute('BEGIN IMMEDIATE')
        current,detail=db.execute('SELECT status,detail FROM dispatch_control').fetchone();detail=json.loads(detail)
        result=_lookup_result(index,rid)
        if current=='ACTIVE' and detail.get('request_id')!=rid:raise PermissionError('WATCHDOG_OTHER_ACTIVE_CLIENT')
        if result is not None and result.get('status') not in {'SENT_UNCONFIRMED','UNKNOWN'} and current!='ACTIVE':return result
        # Keep any original partial/result file. A separate append-only witness
        # records the process outcome; the index remains a no-resend barrier.
        with index.lock:registered=index.db.execute('SELECT 1 FROM requests WHERE id=?',(rid,)).fetchone()
        unknown={'request_id':rid,'status':'SENT_UNCONFIRMED','sent':None,
                 'reason':'OUTER_PROCESS_UNRESOLVED_NO_RETRY','provider_active_count':None,
                 'watchdog':proof,'prior_result_sha256':digest(result) if result else None}
        if registered:
            write(index.root/rid/'watchdog-unresolved.json',unknown)
            with index.lock:index.db.execute('UPDATE requests SET status=?,result=? WHERE id=?',('SENT_UNCONFIRMED',json.dumps(unknown),rid))
        if db.execute('SELECT 1 FROM reservations WHERE id=?',(rid,)).fetchone():
            db.execute('UPDATE reservations SET status=?,evidence=? WHERE id=?',('SENT_UNCONFIRMED',json.dumps({'watchdog_sha256':digest(unknown)}),rid))
        gate._record(db,'FUSED',{'reason':'WATCHDOG_UNRESOLVED','request_id':rid,'result_sha256':digest(unknown),'provider_active_count':None})
        return unknown

class WatchdogNextLiveClient(NextLiveClient):
    def physical_call(self,request,kind,input_measurement):
        if kind not in {'G','COUNT'}:raise PermissionError('WATCHDOG_NO_NEW_E')
        validate(self.transport.existing.config.get('timeout_profile'))
        # Preflight is already complete in the trusted parent. The child issues
        # its own short-lived token (gcloud 45s); no cached token is transferred.
        credentials=self.transport.existing.token_source
        if credentials.cached is not None:raise PermissionError('WATCHDOG_NO_CACHED_CREDENTIAL_TRANSFER')
        s=self.budget.state;identity=self.budget.identity();rid=request['request_id']
        proof=run_process(_call,(str(s.root),s.policy,s.authority,self.budget.scope,
            self.budget.config['reservation_microusd'],identity,str(self.index.root),credentials,
            self.binding,request,kind,input_measurement),PROFILE[kind+'_watchdog_seconds'])
        # The archived proof is separate from the request's HTTP records.
        path=self.index.root/('watchdog-'+rid+'.json')
        write(path,proof)
        if proof['exitcode']==0 and not proof['timed_out']:
            result=_lookup_result(self.index,rid)
            if result is not None:return result
        return reconcile_exit(s,self.index,rid,proof)
