"""Deterministic finite slots, synthetic inputs, exact unapproved host proposal."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import json,os,platform,random,subprocess,sys
from rcwg_native.evidence import ROOT,canonical,sha,write,read,bootstrap
from rcwg_exec.demo import prepare_fixture
from rcwg_native.adapter import lower
from rcwg_native.supervisor import binary_binding

CONTROLLERS=['cpu','memory','io','pids']
def host():
    def read_text(path):
        try:return Path(path).read_text()
        except OSError as e:return {'missing':type(e).__name__}
    root=Path('/sys/fs/cgroup');cg=read_text('/proc/self/cgroup');paths=[root]
    if isinstance(cg,str):paths +=[root/cg.strip().split('::')[-1].lstrip('/')]
    uid=os.getuid();paths +=[root/f'user.slice/user-{uid}.slice/user@{uid}.service']
    return {'identity':{'machine_id_sha256':sha(Path('/etc/machine-id').read_bytes()),'boot_id_sha256':sha(Path('/proc/sys/kernel/random/boot_id').read_bytes()),
            'uid':uid,'gid':os.getgid(),'kernel':platform.release(),'systemd':subprocess.check_output(['systemctl','--version'],text=True).splitlines()[0],
            'python':platform.python_version(),'affinity':sorted(os.sched_getaffinity(0)),'cwd':str(ROOT),'architecture':platform.machine()},
        'memory':read_text('/proc/meminfo'),'mountinfo':read_text('/proc/self/mountinfo'),'self_cgroup':cg,
        'controllers':{str(p):{k:read_text(p/k) for k in ['cgroup.controllers','cgroup.subtree_control','cgroup.procs']} for p in paths},
        'cpu_pressure':read_text('/proc/pressure/cpu'),'memory_pressure':read_text('/proc/pressure/memory'),'formal_ready':False,'cgroup_writes':0}

def slots():
    grid=read(ROOT/'specs/native001/test_manifest.json')['resource_pair_plan'];pairs=[]
    for seed,n,k,mem,alg,rep in product(grid['seeds'],grid['rows'],grid['k'],grid['memory_bytes'],grid['implementation_pairs'],range(grid['repeats'])):
        pairs.append({'seed':seed,'rows':n,'k':k,'memory_max':mem,'algorithms':alg,'repeat':rep})
    rng=random.Random(grid['run_order_seed']);rng.shuffle(pairs);out=[]
    for i,pair in enumerate(pairs):
        order=list(pair['algorithms']);rng.shuffle(order)
        for j,algo in enumerate(order):out.append({'run_id':f'n4-resource-{i:03d}-{j}','case':'C10','category':'resource','pair_id':f'R{i:03d}',**pair,'algorithm':algo,'sampler':True,'mode':'f1','batch':1,'timeout_s':20.0,'children_max':0,'allocation_max_bytes':134217728})
    calibration=[]
    cases=[('C01','noop',1),('C02','cpu',4),('C03','spike',1),('C04','descendant',1),('C05','oom',1),('C06','wait',1),('C06','wait',1)]
    for i,(case,mode,batch) in enumerate(cases):
        for rep in range(3):calibration.append({'run_id':f'n4-cal-{i}-{rep}','case':case,'category':'calibration','mode':mode,'batch':batch,'sampler':True,'memory_max':67108864 if case=='C05' else 134217728,'timeout_s':0.3 if i==5 else 20.0,'cancel_after_s':0.2 if i==6 else None,'children_max':2 if mode=='descendant' else (1 if mode=='wait' else 0),'allocation_max_bytes':100663296 if mode=='oom' else 33554432,'repeat':rep})
    families={'cpu':4,'stream':4,'fanout':4,'io':32,'short':128};overhead=[];warmup=[]
    for family,batch in families.items():
        for sample in [False,True]:warmup.append({'run_id':f'n4-warm-{family}-{int(sample)}','case':'C08','category':'warmup','mode':family,'batch':batch,'sampler':sample,'memory_max':134217728,'timeout_s':20.0,'children_max':2 if family=='fanout' else 0,'allocation_max_bytes':33554432})
        for rep in range(20):
            order=[False,True];rng.shuffle(order)
            for sample in order:overhead.append({'run_id':f'n4-overhead-{family}-{rep:02d}-{int(sample)}','case':'C08','category':'calibration','mode':family,'batch':batch,'sampler':sample,'memory_max':134217728,'timeout_s':20.0,'children_max':2 if family=='fanout' else 0,'allocation_max_bytes':33554432,'pair_id':f'O-{family}-{rep}','repeat':rep})
    integration=[]
    for algo in ['full_sort','streaming_heap']:
        for rep in range(3):integration.append({'run_id':f'n4-f1-{algo}-{rep}','case':'C09','category':'calibration','mode':'f1','batch':1,'sampler':True,'memory_max':134217728,'timeout_s':20.0,'children_max':0,'allocation_max_bytes':134217728,'seed':17,'rows':1024,'k':8,'algorithm':algo,'repeat':rep})
    faults=[{'run_id':f'n4-fault-{fault}','case':'C07','category':'calibration','mode':'noop','batch':1,'sampler':True,'memory_max':134217728,'timeout_s':2.0,'children_max':0,'allocation_max_bytes':0,'fault':fault} for fault in ['collection','seal','controller']]
    # Expected infrastructure faults are last; first real facility failure stops the batch.
    result=calibration+warmup+overhead+integration+out+faults
    for i,s in enumerate(result):
        s.update(sequence=i,cpu_quota_us=100000,cpu_period_us=100000,threads=1,swap_max=0,pids_max=8,
                 output_max_bytes=16777216,status='NOT_RUN',budget_within=None,formal_ready=False)
        s['expected']={'worker':'calibration' if s['mode']!='f1' else 'f1','semantic_oracle':'independent frozen input answer' if s['mode']=='f1' else 'fixed source workload and mode/batch result',
            'terminal':('PROCESS_FAILED_WITH_OOM_EVIDENCE_REQUIRED' if s['case']=='C05' else ('CANCELLED' if s.get('cancel_after_s') else ('TIMEOUT' if s['case']=='C06' else ('INFRA_FAILURE' if s.get('fault') else 'COMPLETED')))),
            'empty_group':True,'measurement_scope':'fresh per-run cgroup; launcher+worker+descendants',
            'tolerance_profile':s['case'],'repeats_in_manifest':20 if s['run_id'].startswith('n4-overhead') else (3 if s['case'] in ['C01','C02','C03','C04','C05','C06','C09','C10'] else 1)}
    return result

def freeze(output,native_build,n4_build):
    out=bootstrap(output);cap=host();write(out/'HOST_CAPABILITY.json',cap)
    if cap['identity']['python']!='3.12.14':raise RuntimeError('TARGET_PYTHON_REQUIRED')
    binary,native=binary_binding(native_build,'performance');nb=read(Path(n4_build)/'N4_BUILD.json')
    binaries={'f1':{'path':str(binary),'sha256':sha(binary.read_bytes()),'build':native}}
    for key,record in nb['binaries'].items():
        p=Path(n4_build).absolute()/record['name']
        if sha(p.read_bytes())!=record['sha256']:raise ValueError('N4_BINARY_MISMATCH')
        binaries[key]={'path':str(p),'sha256':record['sha256'],'build':record}
    for name,digest in nb['source'].items():
        if sha((ROOT/name).read_bytes())!=digest:raise ValueError('N4_SOURCE_MISMATCH')
    allslots=slots();inputs={};fixtures={}
    for s in allslots:
        if s['mode']!='f1':continue
        key=(s['seed'],s['rows'],s['k'])
        if key not in fixtures:fixtures[key]=prepare_fixture(out/('fixture-%s-%s-%s'%key),n=s['rows'],k=s['k'],seed=s['seed'])
        task,plans,recipe,data=fixtures[key];task=deepcopy(task);task['resources']['worker_memory_limit_bytes']=s['memory_max'];task['resources']['wall_timeout_s']=s['timeout_s']
        plan=deepcopy(plans['streaming_heap'])
        fixed={'filter':'scalar','top_k':'streaming_heap','project':'column_view'}
        algo=s['algorithm'];operator='top_k' if algo in ['full_sort','streaming_heap'] else ('filter' if algo in ['scalar','vectorized'] else 'project');fixed[operator]=algo
        for node in plan['nodes']:
            if node['operator'] in fixed:node['implementation']=fixed[node['operator']]
        request=lower(task,plan,locations={task['datasets'][0]['id']:data},allowed_root=out,ident=s['run_id'],mode='performance')['request']
        # Expected answers are computed from synthetic input, independently of measured counters.
        rows=[json.loads(line) for line in data.read_text().splitlines()]
        gold=[{'id':r['id'],'score':r['score']} for r in sorted((r for r in rows if r['eligible']),key=lambda r:(-r['score'],r['id']))[:s['k']]]
        bundle={'task':task,'workir':plan,'request':request,'gold':gold,'source_sha256':sha(data.read_bytes()),'source_path':str(data),'fixed_branches':fixed}
        bp=out/(s['run_id']+'.input.json');write(bp,bundle);s['input_path']=str(bp);s['input_sha256']=sha(bp.read_bytes());inputs[str(bp)]=s['input_sha256'];inputs[str(data)]=sha(data.read_bytes())
    manifest={'revision':'N4_EXPECTED_V1','slots':allslots,'counts':{c:sum(s['category']==c for s in allslots) for c in ['calibration','warmup','resource']},
              'cache_policy':'No drop_caches; natural warm/mixed WSL page cache; adjacent pairs, all parsing/hash/schema work inside worker. Shared cache charges are host dependent.',
              'data_generator':'rcwg_exec.demo.prepare_fixture; score seeded integers cast float; id unique shuffled; eligible id%3 !=0, first row forced ineligible; 3 columns JSONL variable encoded width.',
              'row_width':'Int64 id + Float64 score + Bool eligible; exact encoded bytes and hash in each frozen input',
              'overhead':{'families':5,'pairs_per_family':20,'bootstrap':10000,'seed':4901,'order_seed':901,'threshold':0.03,'sampler_ms':100,'formal_repeats_unchanged':True},
              'tolerances':{'cpu_relative_error':0.20,'spike_peak_min_bytes':16777216,'spike_peak_max_bytes':33554432,'descendant_peak_min_bytes':16777216,'cpu_affinity_exact':True,'memory_sample_may_miss_short_spike':True},'formal_ready':False}
    write(out/'EXPECTED_MANIFEST.json',manifest)
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0');source={p:sha((ROOT/p).read_bytes()) for p in tracked if p}
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();service='rcwg-native001-n4-'+head[:12]+'.service';root='/sys/fs/cgroup/system.slice/'+service
    plan_path=out/'N4_OWNER_CHANGE_PLAN.json';receipt=out/'OWNER_APPROVAL_RECEIPT.json';runout=ROOT/'runs'/('n4-authorized-'+head[:12])
    invoke=[str(ROOT/'.venv/bin/python'),'-m','rcwg_native_n4.runner','--plan',str(plan_path),'--receipt',str(receipt),'--output',str(runout)]
    command=['sudo','systemd-run','--unit='+service,'--collect','--wait','--service-type=exec','--property=User=zhixuan','--property=Group=zhixuan','--property=Delegate=cpu memory io pids','--property=DelegateSubgroup=controller','--property=RuntimeMaxSec=7200','--property=TimeoutStopSec=10','--property=KillMode=control-group','--property=MemoryMax=1G','--property=MemorySwapMax=0','--property=CPUQuota=200%','--property=TasksMax=64','--working-directory='+str(ROOT),*invoke]
    proposal={'revision':'N4_OWNER_CHANGE_PLAN_V1','approved':False,'status':'PROPOSAL_NOT_EXECUTED','head':head,'source':source,'host':cap['identity'],'binaries':binaries,'inputs':inputs,
              'manifest_path':str(out/'EXPECTED_MANIFEST.json'),'manifest_sha256':sha((out/'EXPECTED_MANIFEST.json').read_bytes()),'service':service,'delegated_root':root,'controllers':CONTROLLERS,
              'run_output':str(runout),'commands':{'start':command,'stop':['sudo','systemctl','stop',service],'reconcile':[str(ROOT/'.venv/bin/python'),'-m','rcwg_native_n4.runner','--reconcile',str(runout),'--plan',str(plan_path)]},
              'max_service_starts':1,'automatic_retries':0,'max_concurrency':1,'counts':manifest['counts'],'workload_total':len(allslots),'global_wall_s':7200,'per_run_wall_s_max':20,
              'outer_memory_max_bytes':1073741824,'outer_cpu_quota_percent':200,'outer_tasks_max':64,'total_output_max_bytes':2147483648,'per_file_output_max_bytes':16777216,
              'scope':'Only dedicated service descendants; no shared root/user@ writes, installs, cloud/API/IAM or global cache changes.',
              'failure_policy':'Readiness mismatch aborts before workload. Infrastructure/archive/controller failure stops batch; read-only reconciliation, no resubmission. Remaining slots NOT_RUN.',
              'receipt_required':{'approved':True,'owner_confirmation':'Explicit owner approval of exact SHA','plan_sha256':'SHA256 of this file','valid_from_utc':'owner receipt UTC','valid_until_utc':'maximum 24 hours later','max_uses':1,'bindings_sha256':sha(canonical({'head':head,'host':cap['identity'],'binaries':binaries,'inputs':inputs,'commands':{'start':command,'stop':['sudo','systemctl','stop',service]},'manifest_sha256':sha((out/'EXPECTED_MANIFEST.json').read_bytes())}))},
              'new_cloud_or_api_usd':0,'cost_scope':'Local only; electricity and existing hardware costs not estimated','formal_ready':False,'budget_within':None,'formal_status':'BLOCKED_NOT_FROZEN'}
    write(plan_path,proposal)
    write(out/'INITIAL_SLOT_STATUS.json',{'slots':[{'run_id':s['run_id'],'status':'NOT_RUN','reason':'HOST_APPROVAL_NOT_GRANTED'} for s in allslots],'expected':len(allslots)})
    print(json.dumps({'plan':str(plan_path),'sha256':sha(plan_path.read_bytes()),'counts':manifest['counts'],'total':len(allslots),'approved':False}))
    return proposal
