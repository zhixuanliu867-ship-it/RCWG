"""Bounded collection; transport-only replacement, every physical attempt retained."""
from pathlib import Path
import sys,json,time,subprocess,os,argparse,collections
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def one(root,jobfile,hard):
 r=Path(root);sys.path.insert(0,str(r/'src'));j=load(jobfile)
 from common import sha
 if not hard:
  from tiered import TierFlow as Flow
 else:
  from dataflow import Flow
 from transport_explicit_mode import RoundClient
 freeze=load(r/'protocol/run_freeze.json');assert sha(r/'protocol/round1.json')==freeze['protocol_sha256'];assert sha(Path(__file__).resolve())==freeze['collector_sha256']
 for rel,h in freeze['source_hashes'].items():assert sha(r/rel)==h,rel
 f=Flow(j['task'],j['episode'],j['worker_slots'],prefix=r/'runs'/j['prefix_episode'] if j['prefix_episode'] else None);write(f.out/'assignment.json',j)
 try:s=f.collect(RoundClient(j['model']),j['max_decisions']);print(json.dumps({'episode':j['episode'],'status':s['status'],'valid':s['quality']['joint_valid']}),flush=True)
 finally:f.close()
def main(root,hard):
 r=Path(root);sys.path.insert(0,str(r/'src'));from transport_explicit_mode import RoundLedger
 p=load(r/'protocol/round1.json');jobs=p['jobs'] if hard else [j for j in p['jobs'] if j['split']==('dev' if os.environ.get('WELD_SPLIT')=='dev' else 'main')]
 selected=os.environ.get('WELD_MODELS')
 if selected:jobs=[j for j in jobs if j['model'] in selected.split(',')]
 for model in set(j['model'] for j in jobs):assert load(r/f'qa/preflight_{model}.json')['ready'],model+' transport preflight not ready'
 logdir=r/'runs/scheduler_logs';logdir.mkdir(exist_ok=True);assign=r/'protocol/assignments';assign.mkdir(exist_ok=True)
 split='dev' if os.environ.get('WELD_SPLIT')=='dev' else 'main'; prefix='dev_' if split=='dev' else ''; manifest_path=r/('qa/'+prefix+'matrix_manifest.json');manifest=load(manifest_path) if manifest_path.exists() else {};active={};done={};pending=[];ledger=RoundLedger();stop=None;last=0;start=time.time()
 def completed(j):
  seq=manifest.get(j['episode'],[])
  if not seq:return False
  lastid=seq[-1];sp=r/'runs'/lastid/'summary.json'
  if not sp.exists():raise RuntimeError('Incomplete retained process requires inspection: '+lastid)
  s=load(sp)
  if s['status']=='BUDGET_EXHAUSTED' and lastid in p.get('transport_admission_replacements',[]):return False
  if s['status']=='TRANSPORT_UNKNOWN' and lastid in p.get('verified_transport_replacements',[]) and len(seq)<p['scheduler']['max_transport_attempts']:return False
  if s['status']=='TRANSPORT_UNKNOWN' and len(seq)<p['scheduler']['max_transport_attempts']:
   reqs=[json.loads(x) for x in (r/'runs'/lastid/'physical_requests.jsonl').read_text(encoding='utf8').splitlines() if x.strip()];err=reqs[-1].get('error','') if reqs else ''
   if err in ('URLError','TimeoutError','RemoteDisconnected','ConnectionResetError','IncompleteRead','HTTP_520','HTTP_521','HTTP_522','HTTP_524','HTTP_429','HTTP_502','HTTP_503','HTTP_504'):return False
  # A transport-replaced initial stage requires continuations from that exact prefix.
  if j['prefix_episode']:
   if j['prefix_episode'] not in done:return False
   previous=load(r/'runs'/lastid/'assignment.json').get('prefix_episode')
   if previous!=done[j['prefix_episode']]:return False
  done[j['episode']]=lastid;return True
 for j in jobs:
  if not completed(j):pending.append(j)
 while pending or active:
  b=ledger.summary()
  if b['fuse']:stop=b['fuse']
  if (r/'protocol/STOP_REQUESTED').exists():stop='STOP_REQUESTED'
  while len(active)<(4 if hard else p['scheduler']['global_concurrency']) and pending and not stop:
   occupied=collections.Counter(x['job']['model'] for x in active.values());ix=next((i for i,j in enumerate(pending) if occupied[j['model']]<(4 if hard else p['scheduler'].get('per_model_limits',{}).get(j['model'],p['scheduler']['per_model_concurrency'])) and (not j['prefix_episode'] or j['prefix_episode'] in done)),None)
   if ix is None:break
   original=pending.pop(ix);key=original['episode'];history=manifest.setdefault(key,[]);j=original.copy();j.update(logical_episode=key,attempt_index=len(history),episode=key+('__transport'+str(len(history)) if history else ''),prefix_episode=done.get(original['prefix_episode']) if original['prefix_episode'] else None)
   if (r/'runs'/j['episode']).exists():raise RuntimeError('Do not overwrite '+j['episode'])
   history.append(j['episode']);write(manifest_path,manifest);jf=assign/(j['episode']+'.json');write(jf,j);f=open(logdir/(j['episode']+'.log'),'ab')
   cmd=[sys.executable,str(Path(__file__).resolve()),'--root',str(r),'--job',str(jf)]+(['--hard'] if hard else [])
   proc=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONUTF8':'1'},creationflags=0x08000000);active[j['episode']]={'proc':proc,'log':f,'job':j,'original':original}
  for eid,x in list(active.items()):
   rc=x['proc'].poll()
   if rc is None:continue
   x['log'].close();del active[eid];path=r/'runs'/eid/'summary.json'
   if not path.exists():stop='PROCESS_ERROR:'+eid;continue
   s=load(path)
   if not completed(x['original']):pending.append(x['original'])
   if s['status']=='BUDGET_EXHAUSTED':stop='BUDGET_EXHAUSTED'
  if time.time()-last>15 or not active:
   rows=[load(r/'runs'/eid/'summary.json') for eid in done.values()];b=ledger.summary();b.pop('requests',None)
   progress={'planned':len(jobs),'completed':len(rows),'physical_stages':sum(len(x) for x in manifest.values()),'joint_valid':sum(s['quality']['joint_valid'] for s in rows),'by_model':dict(collections.Counter(load(r/'runs'/eid/'assignment.json')['model'] for eid in done.values())),'statuses':dict(collections.Counter(s['status'] for s in rows)),'running':list(active),'remaining':len(pending),'stop':stop,'elapsed_seconds':time.time()-start,'accounting':b}
   write(r/('qa/'+prefix+'matrix_progress.json'),progress);print(json.dumps({k:progress[k] for k in ['completed','planned','joint_valid','stop']}|{'usd':b['settled_cost_usd']}),flush=True);last=time.time()
  if not active and stop:break
  if not active and pending and not any(not j['prefix_episode'] or j['prefix_episode'] in done for j in pending):raise RuntimeError('Unresolved prefix dependency')
  time.sleep(.5)
 write(r/('qa/'+prefix+'matrix_resolved.json'),done)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--root',required=True);a.add_argument('--job');a.add_argument('--hard',action='store_true');v=a.parse_args();one(v.root,v.job,v.hard) if v.job else main(v.root,v.hard)
