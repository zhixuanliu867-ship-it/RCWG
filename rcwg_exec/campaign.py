"""Fixed-denominator offline attempts and genuine SPEC-B mock generation ingress."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import threading
from rcwg_spec.common import canonical,digest,ContractError
from rcwg_spec.binding import ExpectedManifest
from rcwg_spec.generation import run_mock_generation
from rcwg_exec.context import source_closure
from rcwg_exec.datasets import FileRegistry
from rcwg_exec.errors import ExecFault
from rcwg_exec.journal import Journal,read_json
from rcwg_exec.sealing import bytes_at,reopen_run
from rcwg_exec.store import PrivateStore
from rcwg_exec.supervisor import run_f1_supervised

ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')

@dataclass(frozen=True)
class ExpectedAttempts:
    """Independent immutable snapshot made before generation or worker creation."""
    snapshot:bytes
    @property
    def sha256(self):return hashlib.sha256(self.snapshot).hexdigest()
    def as_dict(self):
        import json
        return json.loads(self.snapshot)


def freeze_attempts(cases):
    rows=[];seen=set();generations={}
    for case in cases:
        ident=case['attempt_id']
        if type(ident) is not str or not ID.fullmatch(ident) or ident in seen:raise ExecFault('ATTEMPT_ID')
        seen.add(ident)
        mode=case.get('protocol','HANDCRAFTED')
        if mode not in {'HANDCRAFTED','P0','P1'}:raise ExecFault('ATTEMPT_PROTOCOL')
        if mode=='HANDCRAFTED':input_identity={'plan_hash':digest(case['plan'])}
        else:
            responses=case['responses']
            if type(responses) is not list or len(responses)!=(1 if mode=='P0' else 2) or any(type(x) is not bytes for x in responses):
                raise ExecFault('ATTEMPT_RESPONSES')
            input_identity={'response_sha256':[hashlib.sha256(x).hexdigest() for x in responses]}
        row={'attempt_id':ident,'protocol':mode,'task_hash':digest(case['task']),**input_identity,
            'generation_id':case.get('generation_id',ident+'.generation'),
            'repeat_id':case.get('repeat_id','r0'),'recipe_hash':digest(case['recipe']),
            'fault_injection':case.get('fault','none'),'cancel_after_s':case.get('cancel_after_s'),
            'max_materialized_rows':case.get('max_materialized_rows',100000)}
        identity=digest({'protocol':mode,'task_hash':row['task_hash'],**input_identity})
        generation_id=row['generation_id']
        if generation_id in generations and generations[generation_id]!=identity:raise ExecFault('GENERATION_REUSE_IDENTITY')
        generations[generation_id]=identity;rows.append(row)
    if not rows:raise ExecFault('ATTEMPTS_EMPTY')
    return ExpectedAttempts(canonical({'version':'EXEC001_EXPECTED_ATTEMPTS_1.0','attempts':rows,
        'fixed_denominator':len(rows),'source_closure':source_closure(),'formal_ready':False}))


def run_campaign(cases,*,output):
    """Execute every predeclared slot once; parse/static/gap failures keep slots.

    This is an engineering campaign, with no statistical metric aggregation.
    Cases and mock responses come from trusted development fixtures, never APIs.
    """
    cases=deepcopy(cases);expected=freeze_attempts(cases);store=PrivateStore(Path(output))
    store.write_bytes('expected_attempts.json',expected.snapshot)
    journal=Journal(store.root/'attempts.journal.jsonl',execution_key=expected.sha256,
                    manifest_hash=expected.sha256,origin='campaign')
    journal.append('campaign_started','RUNNING',{'expected_hash':expected.sha256,'fixed_denominator':len(cases)})
    records=[];generation_cache={}
    try:
        for case,slot in zip(cases,expected.as_dict()['attempts']):
            ident=slot['attempt_id'];attempt=PrivateStore(store.root/ident)
            journal.append('attempt_started','RUNNING',{'attempt_id':ident})
            attempt.write_json('expected_slot.json',slot);generation=None;result=None;timer=None;generated=False
            try:
                task=case['task']
                if slot['protocol']=='HANDCRAFTED':plan=case['plan']
                else:
                    if slot['generation_id'] not in generation_cache:
                        generation_cache[slot['generation_id']]=run_mock_generation(task,protocol=slot['protocol'],responses=case['responses'],
                                                       generation_attempt_id=slot['generation_id'])
                        generated=True
                    generation=deepcopy(generation_cache[slot['generation_id']])
                    attempt.write_json('generation.json',generation)
                    for index,raw in enumerate(case['responses']):attempt.write_bytes('mock-response-'+str(index)+'.bin',raw)
                    # The only physical plan is the exact B parser output.
                    plan=generation['plan']
                if plan is None:
                    result={'status':'MOCK_RESPONSE_INVALID','execution_started':False,'formal_ready':False}
                else:
                    registry=FileRegistry(task,case['locations'],allowed_root=case['allowed_root'])
                    cancel=None
                    if slot['cancel_after_s'] is not None:
                        cancel=threading.Event();timer=threading.Timer(slot['cancel_after_s'],cancel.set);timer.start()
                    result=run_f1_supervised(task,plan,registry=registry,recipe=case['recipe'],output=attempt.root/'execution',
                        record_id=ident,generation_id=slot['generation_id'],repeat_id=slot['repeat_id'],
                        max_materialized_rows=slot['max_materialized_rows'],_fault=slot['fault_injection'],cancel_event=cancel)
            except (ExecFault,ContractError,OSError,ValueError,TypeError,KeyError) as exc:
                result={'status':'ATTEMPT_FACILITY_ERROR','terminal_status':'INFRA_FAILURE','verification':{'status':'UNKNOWN'},
                        'failure':{'code':getattr(exc,'code',type(exc).__name__),'attribution':'facility'},
                        'execution_started':None if (attempt.root/'execution').exists() else False,
                        'partial_execution_evidence':(attempt.root/'execution').exists(),'formal_ready':False}
            finally:
                if timer is not None:timer.cancel();timer.join()
            record={'attempt_id':ident,'expected_hash':expected.sha256,'slot_hash':digest(slot),
                'protocol':slot['protocol'],'generation_id':slot['generation_id'],'repeat_id':slot['repeat_id'],
                'generation_attempts':int(generated),'mock_requests':generation['mock_requests'] if generated else 0,
                'generation_observation':'CREATED' if generated else 'REUSED' if generation else 'HANDCRAFTED',
                'execution_attempts':int(result['execution_started']) if result.get('execution_started') is not None else None,'real_requests':0,
                'outcome':result.get('terminal_status',result['status']),
                'verification':result.get('verification',{}).get('status','UNKNOWN'),'result':result,'formal_ready':False}
            record_hash=attempt.write_json('attempt.json',record)
            files={str(p.relative_to(attempt.root)):hashlib.sha256(bytes_at(p)).hexdigest()
                   for p in sorted(attempt.root.rglob('*')) if p.is_file()}
            records.append({'attempt_id':ident,'record_sha256':record_hash,'files':files,
                            'outcome':record['outcome'],'verification':record['verification']})
            journal.append('attempt_finished',record['outcome'],{'attempt_id':ident,'record_sha256':record_hash})
        journal.append('campaign_finished','COMPLETED',{'observed_count':len(records)})
    finally:journal.close()
    summary={'version':'EXEC001_CAMPAIGN_1.0','expected_hash':expected.sha256,'fixed_denominator':len(cases),
             'observed_count':len(records),'records':records,'formal_ready':False,'real_requests':0,
             'journal_sha256':hashlib.sha256(bytes_at(store.root/'attempts.journal.jsonl')).hexdigest()}
    summary_hash=store.write_json('campaign.json',summary)
    reread=reopen_campaign(store.root,expected=expected,summary_sha256=summary_hash)
    return {'status':'EXEC001_CAMPAIGN_SEALED','expected_hash':expected.sha256,'summary_sha256':summary_hash,
            'fixed_denominator':len(cases),'outcomes':[{k:r[k] for k in ('attempt_id','outcome','verification')} for r in records],
            'reread':reread,'formal_ready':False,'real_requests':0}


def reopen_campaign(directory,*,expected,summary_sha256):
    directory=Path(directory)
    if bytes_at(directory/'expected_attempts.json')!=expected.snapshot:raise ExecFault('ATTEMPT_MANIFEST_CHANGED')
    if hashlib.sha256(bytes_at(directory/'campaign.json')).hexdigest()!=summary_sha256:raise ExecFault('CAMPAIGN_SEAL_CHANGED')
    summary=read_json(directory/'campaign.json');slots=expected.as_dict()['attempts']
    if summary['expected_hash']!=expected.sha256 or summary['fixed_denominator']!=len(slots):raise ExecFault('CAMPAIGN_DENOMINATOR')
    if [r['attempt_id'] for r in summary['records']]!=[s['attempt_id'] for s in slots]:raise ExecFault('CAMPAIGN_SLOTS')
    if hashlib.sha256(bytes_at(directory/'attempts.journal.jsonl')).hexdigest()!=summary['journal_sha256']:raise ExecFault('CAMPAIGN_JOURNAL_CHANGED')
    missing=[];observed=[]
    for slot,row in zip(slots,summary['records']):
        folder=directory/slot['attempt_id'];file=folder/'attempt.json'
        if not file.exists():missing.append(slot['attempt_id']);continue
        actual={str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()}
        if actual!=set(row['files']):raise ExecFault('ATTEMPT_FILE_SET')
        for name,h in row['files'].items():
            if not (folder/name).resolve().is_relative_to(folder.resolve()):raise ExecFault('ATTEMPT_FILE_PATH')
            if hashlib.sha256(bytes_at(folder/name)).hexdigest()!=h:raise ExecFault('ATTEMPT_FILE_CHANGED')
        if hashlib.sha256(bytes_at(file)).hexdigest()!=row['record_sha256']:raise ExecFault('ATTEMPT_RECORD_CHANGED')
        record=read_json(file)
        if record['slot_hash']!=digest(slot) or record['expected_hash']!=expected.sha256:raise ExecFault('ATTEMPT_BINDING')
        result=record['result']
        if 'seal_sha256' in result:
            manifest=ExpectedManifest(bytes_at(folder/'execution/expected_manifest.json'))
            reopen_run(folder/'execution',manifest=manifest,seal_sha256=result['seal_sha256'])
        observed.append({'attempt_id':slot['attempt_id'],'outcome':record['outcome'],'verification':record['verification']})
    return {'status':'CAMPAIGN_REOPENED' if not missing else 'CAMPAIGN_INCOMPLETE','fixed_denominator':len(slots),
            'observed_count':len(observed),'missing_attempt_ids':missing,
            'unknown_count':len(missing)+sum(r['verification']=='UNKNOWN' for r in observed),'formal_ready':False}
