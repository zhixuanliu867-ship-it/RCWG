"""Gate, then run the frozen balanced matrix in isolated episode processes."""
import argparse,subprocess,time,os,sys,datetime
from common import *

def gate():
    from acceptance import contracts,runtime_controls
    from round_protocol import TASKS
    rows=contracts('R1_GATE',only=TASKS)
    runtime=load(ROOT/'qa/R1_GATE_runtime.json')['checks'] if (ROOT/'qa/R1_GATE_runtime.json').exists() else runtime_controls('R1_GATE')
    # Native exactness, coverage, evidence identity and update behavior are already
    # instrumented; this pass exercises every condition selected for the paid matrix.
    source=Path(config()['baseline_root']);old=load(source/'manifest.json');files={x['path']:x['sha256'] for x in old['files']};mismatches=[]
    for folder in ['tasks','private','agent_views','assets']:
        for p in (ROOT/folder).rglob('*'):
            rel=p.relative_to(ROOT).as_posix()
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc' and (rel not in files or sha(p)!=files[rel]):mismatches.append(rel)
    judge_files=['src/evaluator.py','src/metrics.py','src/adapters.py','src/runtime.py','src/common.py','src/impact.py','vendor/native_bridge.py']
    for rel in judge_files:
        if sha(ROOT/rel)!=files[rel]:mismatches.append(rel)
    result={'pass':all(x['pass'] for x in rows+runtime) and not mismatches,'task_count':len(rows),'passed_tasks':sum(x['pass'] for x in rows),'contract_checks':sum(len(x['checks']) for x in rows),'runtime_passed':sum(x['pass'] for x in runtime),'runtime_total':len(runtime),'sealed_input_or_judge_changes':mismatches,'primary_limitations':['incomplete investigation and evidence integration','stale conclusion use and failed state reconciliation','inherited wrong claims and copied-source repetition'],'decision':'Enter real API experiments only if the task and negative controls pass. Hypotheses may be disconfirmed by competent model behavior.'}
    write(ROOT/'qa/round_entry_gate.json',result);print(dump(result),flush=True)
    if not result['pass']:raise SystemExit(1)

def episode(eid):
    from runtime import Runtime
    from round_transport import RoundClient
    protocol=load(ROOT/'protocol/round1.json');job=next(x for x in protocol['jobs'] if x['episode']==eid)
    if not load(ROOT/'qa/round_entry_gate.json')['pass']:raise RuntimeError('Entry gate failed')
    out=ROOT/'runs'/eid
    if (out/'summary.json').exists():print('ALREADY_RECORDED',eid);return
    if out.exists():raise RuntimeError('Partial episode retained; do not overwrite')
    for rel,h in protocol['source_hashes'].items():
        if sha(ROOT/rel)!=h:raise RuntimeError('Frozen source changed: '+rel)
    client=RoundClient(job['manager'],job['worker']);rt=Runtime(job['task'],eid,workers=2)
    write(out/'experiment_assignment.json',{**job,'manager_model':protocol['models'][job['manager']],'worker_model':protocol['models'][job['worker']],'protocol_sha256':sha(ROOT/'protocol/round1.json')})
    try:
        rt.run_agent(client,max_calls=40,manager_turns=10,worker_turns=8)
        s=load(out/'summary.json');print(dump({'episode':eid,'status':s['status'],'success':s['evaluation']['success'],'calls':s['model_calls']}),flush=True)
    finally:rt.close()

def run():
    from round_transport import RoundLedger
    if not load(ROOT/'qa/round_entry_gate.json')['pass']:raise RuntimeError('Entry gate failed')
    if not all(x['ready'] for x in load(ROOT/'qa/model_preflight.json')):raise RuntimeError('Three model preflight incomplete')
    protocol=load(ROOT/'protocol/round1.json');ledger=RoundLedger();jobs=protocol['jobs'];pending=[x for x in jobs if not (ROOT/'runs'/x['episode']/'summary.json').exists()];active={};terminal=[]
    logdir=ROOT/'runs/scheduler_logs';logdir.mkdir(exist_ok=True);started=time.time();last=0
    while pending or active:
        s=ledger.summary();blocked=s['fuse'] or s['committed_usd']>=config()['round_budget_usd']-1
        while pending and len(active)<3 and not blocked:
            job=pending.pop(0);eid=job['episode'];log=open(logdir/f'{eid}.log','ab');proc=subprocess.Popen([sys.executable,str(Path(__file__)), '--episode',eid],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONUTF8':'1'},creationflags=0x08000000);active[eid]=(proc,log,job,time.time());print('START',eid,flush=True)
        for eid,(proc,log,job,t0) in list(active.items()):
            code=proc.poll()
            if code is None:continue
            log.close();p=ROOT/'runs'/eid/'summary.json';summary=load(p) if p.exists() else None;row={'episode':eid,'exit_code':code,'summary_exists':bool(summary),'success':summary['evaluation']['success'] if summary else None,'status':summary['status'] if summary else 'PROCESS_ERROR','seconds':time.time()-t0};terminal.append(row);del active[eid];print('DONE',dump(row),flush=True)
        if time.time()-last>15 or not active:
            s=ledger.summary();summaries=[load(ROOT/'runs'/j['episode']/'summary.json') for j in jobs if (ROOT/'runs'/j['episode']/'summary.json').exists()]
            progress={'planned':len(jobs),'completed':len(summaries),'running':list(active),'pending':len(pending),'task_successes':sum(x['evaluation']['success'] for x in summaries),'settled_usd':s['settled_cost_usd'],'unknown_reserved_usd':s['unresolved_reserved_usd'],'committed_usd':s['committed_usd'],'fuse':s['fuse'],'elapsed_seconds':time.time()-started,'process_outcomes':terminal};write(ROOT/'qa/round_progress.json',progress);write(ROOT/'runs/round_accounting.json',s);last=time.time()
        if blocked and not active:break
        time.sleep(1)
    write(ROOT/'qa/round_scheduler_final.json',{'planned':len(jobs),'remaining_unstarted':pending,'process_outcomes':terminal,'accounting':ledger.summary()});print('ROUND_DISPATCH_COMPLETE',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gate',action='store_true');p.add_argument('--run',action='store_true');p.add_argument('--episode');a=p.parse_args()
    if a.gate:gate()
    elif a.episode:episode(a.episode)
    elif a.run:run()
    else:p.print_help()
