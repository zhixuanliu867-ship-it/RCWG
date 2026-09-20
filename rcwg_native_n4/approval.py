"""Read-only exact receipt verification. This module never creates an approval."""
from datetime import datetime,timezone
from pathlib import Path
import os,subprocess
from rcwg_native.evidence import ROOT,canonical,sha,read,no_symlink,write
from .plan import host

def validate(plan_path,receipt_path,*,now=None,observed_host=None,check_files=True):
    plan_path=no_symlink(plan_path);receipt_path=no_symlink(receipt_path)
    plan=read(plan_path);receipt=read(receipt_path);now=now or datetime.now(timezone.utc)
    if plan.get('approved') is not False or plan.get('revision')!='N4_OWNER_CHANGE_PLAN_V1':raise ValueError('IMMUTABLE_UNAPPROVED_PROPOSAL_REQUIRED')
    if receipt.get('approved') is not True or receipt.get('owner_confirmation')!='Explicit owner approval of exact SHA':raise ValueError('EXPLICIT_OWNER_RECEIPT_REQUIRED')
    if receipt.get('plan_sha256')!=sha(plan_path.read_bytes()) or receipt.get('bindings_sha256')!=plan['receipt_required']['bindings_sha256']:raise ValueError('APPROVAL_BINDING_MISMATCH')
    start=datetime.fromisoformat(receipt['valid_from_utc']);end=datetime.fromisoformat(receipt['valid_until_utc'])
    if not start.tzinfo or not end.tzinfo or not 0<(end-start).total_seconds()<=86400 or not start<=now<=end:raise ValueError('APPROVAL_EXPIRED_OR_INVALID')
    if receipt.get('max_uses')!=1 or plan['max_service_starts']!=1 or plan['automatic_retries']!=0:raise ValueError('APPROVAL_COUNT_MISMATCH')
    if (observed_host if observed_host is not None else host()['identity'])!=plan['host']:raise ValueError('HOST_BINDING_MISMATCH')
    if check_files:
        head=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
        if head!=plan['head']:raise ValueError('HEAD_BINDING_MISMATCH')
        files={str(ROOT/p):h for p,h in plan['source'].items()};files.update(plan['inputs']);files.update({r['path']:r['sha256'] for r in plan['binaries'].values()});files[plan['manifest_path']]=plan['manifest_sha256']
        for path,digest in files.items():
            if sha(no_symlink(path).read_bytes())!=digest:raise ValueError('CONTENT_BINDING_MISMATCH:'+path)
    manifest=read(plan['manifest_path'])
    ids=[s['run_id'] for s in manifest['slots']]
    if len(ids)!=plan['workload_total'] or len(set(ids))!=len(ids):raise ValueError('SLOT_DENOMINATOR_INVALID')
    required={'run_id','case','category','sequence','memory_max','cpu_quota_us','cpu_period_us','swap_max','pids_max','threads','timeout_s','children_max','allocation_max_bytes','output_max_bytes','mode','batch','sampler'}
    for s in manifest['slots']:
        if not required<=s.keys() or any(s[k] is None for k in required):raise ValueError('INCOMPLETE_SLOT')
        if not 0<s['timeout_s']<=plan['per_run_wall_s_max'] or s['threads']!=1 or s['pids_max']>8 or s['children_max']>2 or s['memory_max']>134217728:raise ValueError('SLOT_LIMIT_INVALID')
    return plan,receipt,manifest

def claim(path,plan_path,receipt):
    # O_EXCL + fsync; an uncertain/crashed service still consumes the only use.
    return write(path,{'plan_sha256':sha(Path(plan_path).read_bytes()),'receipt':receipt,'pid':os.getpid(),'uses':1})
