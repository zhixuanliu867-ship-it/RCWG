"""One receipt-bound transient service, finite slots, outer watchdog and stop."""
from pathlib import Path
import argparse,json,os,signal,sys,threading,time
from rcwg_native.evidence import ROOT,write,read,sha,canonical,no_symlink
from .approval import validate,claim
from .plan import freeze,CONTROLLERS
from .runtime import one,context_snapshot
from .evidence import reconcile

def readiness(plan):
    root=no_symlink(plan['delegated_root']);expected='/system.slice/'+plan['service']+'/controller'
    if Path('/proc/self/cgroup').read_text().strip()!='0::'+expected:raise ValueError('DEDICATED_SERVICE_MEMBERSHIP_REQUIRED')
    if root.stat().st_uid!=os.getuid() or (root/'cgroup.procs').read_text().strip():raise ValueError('DELEGATION_STRUCTURE_INVALID')
    available=set((root/'cgroup.controllers').read_text().split())
    if not set(CONTROLLERS)<=available:raise ValueError('CONTROLLERS_NOT_AVAILABLE:'+','.join(sorted(set(CONTROLLERS)-available)))
    # Only the approved dedicated service root; never any shared ancestor.
    with (root/'cgroup.subtree_control').open('w') as f:f.write(' '.join('+'+c for c in CONTROLLERS))
    enabled=set((root/'cgroup.subtree_control').read_text().split())
    if not set(CONTROLLERS)<=enabled:raise ValueError('CONTROLLERS_NOT_ENABLED')
    for name,value in [('memory.max','1073741824'),('memory.swap.max','0'),('pids.max','64'),('cpu.max','200000 100000')]:
        if (root/name).read_text().strip()!=value:raise ValueError('OUTER_LIMIT_MISMATCH:'+name)
    return {'available':sorted(available),'enabled':sorted(enabled),'root':str(root),'self_membership':expected,'counters':context_snapshot(root),'status':'READY_ENGINEERING_ONLY'}

def watchdog(function,deadline,*,size_check=lambda:False):
    """Single-thread fork, parent deadline active before child can call Popen."""
    if threading.active_count()!=1:raise ValueError('SINGLE_THREAD_CONTROLLER_REQUIRED')
    started=time.monotonic();pid=os.fork()
    if pid==0:
        try:os.setsid();function();os._exit(0)
        except BaseException:os._exit(90)
    why=None;status=None
    while True:
        done,status=os.waitpid(pid,os.WNOHANG)
        if done:break
        if time.monotonic()>=deadline:why='EXTERNAL_WATCHDOG';break
        if size_check():why='OUTPUT_CAP';break
        time.sleep(0.02)
    if why:
        try:os.killpg(pid,signal.SIGKILL)
        except ProcessLookupError:pass
        _,status=os.waitpid(pid,0)
    return {'child_pid':pid,'exitcode':os.waitstatus_to_exitcode(status),'reason':why,'wall_s':time.monotonic()-started}

def external_finalize(plan,slot,out):
    """Approved emergency stop, then durable observations before optional removal."""
    group=no_symlink(Path(plan['delegated_root'])/slot['run_id']);record={'group':str(group),'exists':group.exists(),'errors':[],'empty':None,'removed':False}
    if group.exists():
        identity=(group.stat().st_dev,group.stat().st_ino)
        try:
            with (group/'cgroup.kill').open('w') as f:f.write('1')
        except OSError as e:record['errors'].append('kill:'+str(e))
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            try:
                raw=(group/'cgroup.events').read_text();record['events_raw']=raw
                if 'populated 0' in raw:record['empty']=True;break
            except OSError as e:record['errors'].append('events:'+str(e));break
            time.sleep(0.01)
        record['final_context']=context_snapshot(group)
        write(out/'EXTERNAL_FINAL_BEFORE_REMOVE.json',record)
        if record['empty'] and (group.stat().st_dev,group.stat().st_ino)==identity:
            try:group.rmdir();record['removed']=True
            except OSError as e:record['errors'].append('remove:'+str(e))
    write(out/'EXTERNAL_CLEANUP.json',record)
    return record

def run(plan_path,receipt_path,output):
    plan,receipt,manifest=validate(plan_path,receipt_path)
    out=no_symlink(output)
    if str(out)!=plan['run_output']:raise ValueError('OUTPUT_BINDING_MISMATCH')
    # The claim is outside the transient service; persists even if service crashes.
    claim(Path(plan_path).parent/'SERVICE_USE.json',plan_path,receipt)
    out.mkdir(mode=0o700);write(out/'EXPECTED_MANIFEST.json',manifest);write(out/'PLAN_ANCHOR.json',{'sha256':sha(Path(plan_path).read_bytes()),'receipt':receipt})
    deadline=time.monotonic()+plan['global_wall_s']-10
    try:write(out/'READINESS.json',readiness(plan))
    except Exception as e:
        write(out/'READINESS_FAILURE.json',{'error':str(e)});write(out/'RECONCILIATION.json',reconcile(manifest,out));return 2
    def full():return sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>plan['total_output_max_bytes']-33554432
    for slot in manifest['slots']:
        if time.monotonic()>=deadline or full():break
        d=out/slot['run_id'];d.mkdir(mode=0o700);write(d/'CLAIM.json',slot)
        observation=watchdog(lambda:one(slot,plan,d,(plan_path,receipt_path)),min(deadline,time.monotonic()+slot['timeout_s']+10),size_check=full)
        write(d/'WATCHDOG.json',observation)
        if observation['exitcode']!=0:
            external_finalize(plan,slot,d);break
        result=read(d/'terminal.json')
        if result['terminal_status']=='INFRA_FAILURE' or (d/'ARCHIVE_FAILURE.json').exists():break
    final=reconcile(manifest,out);write(out/'RECONCILIATION.json',final)
    from .assess import assess
    write(out/'CALIBRATION_RESULTS.json',assess(manifest,final))
    return 0

def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path);p.add_argument('--receipt',type=Path);p.add_argument('--output',type=Path);p.add_argument('--reconcile',type=Path);p.add_argument('--freeze',type=Path);p.add_argument('--native-build',type=Path);p.add_argument('--n4-build',type=Path);a=p.parse_args()
    if a.freeze:return freeze(a.freeze,a.native_build,a.n4_build) and 0
    if a.reconcile:
        plan=read(a.plan);manifest=read(plan['manifest_path']);print(json.dumps(reconcile(manifest,a.reconcile),indent=2));return 0
    if not all([a.plan,a.receipt,a.output]):p.error('plan, receipt and exact output required')
    return run(a.plan,a.receipt,a.output)
if __name__=='__main__':raise SystemExit(main())
