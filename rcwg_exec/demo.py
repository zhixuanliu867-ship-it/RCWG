"""New synthetic development fixtures, distinct from the protected task matrix."""
from copy import deepcopy
import hashlib
from pathlib import Path
import random
from rcwg_spec.common import load,canonical,digest
from .verifier import RECIPE
from .datasets import FileRegistry
from .runner import run_f1_reference

ROOT=Path(__file__).resolve().parents[1]

def prepare_fixture(directory:Path,*,n=257,k=20,seed=17,rows=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    if rows is None:
        rng=random.Random(seed)
        ids=list(range(n));rng.shuffle(ids)
        rows=[{'id':i,'score':float(rng.randrange(-50,51)), 'eligible':bool(i%3)} for i in ids]
        # Guarantees a semantic counterexample to dropping eligibility.
        if rows:rows[0]={'id':rows[0]['id'],'score':10000.0,'eligible':False}
    raw=b''.join(canonical(r)+b'\n' for r in rows)
    data=directory/'records.jsonl';data.write_bytes(raw);data.chmod(0o600)
    task=load(ROOT/'specs/reference_v1_0/examples/task_input.json')
    task['task_id']='F1-EXEC001-DEVELOPMENT';task['notes']='Synthetic development fixture; not a formal benchmark instance.'
    task['instruction']='Keep eligible records; return up to k by score descending, id ascending, fields id and score.'
    source=task['datasets'][0];source['revision']='exec001-dev-v1';source['kind']='table';source['schema_source']='public:synthetic-dev'
    source['stats']={'row_count':len(rows),'estimate_source':'synthetic_exact_metadata'}
    source['data_sha256']=hashlib.sha256(raw).hexdigest()
    task['resources']={'cpu_slots':1,'worker_memory_limit_bytes':128*1024*1024,'wall_timeout_s':30}
    task['output_contract'].update(k=k,id='exact_ordered_topk_v1')
    recipe={'revision':RECIPE,'source_id':source['id'],'source_sha256':source['data_sha256'],
            'task_input_hash':digest(task),'k':k,'fields':['id','score']}
    base=load(ROOT/'specs/reference_v1_0/examples/workflow_topk.json');base['task_id']=task['task_id']
    base['nodes'][2]['params']['k']=k
    plans={}
    for implementation in ('streaming_heap','full_sort'):
        plan=deepcopy(base);plan['nodes'][2]['implementation']=implementation;plans[implementation]=plan
    wrong=deepcopy(base);wrong['nodes']=[n for n in wrong['nodes'] if n['operator']!='filter'];wrong['nodes'][1]['inputs']['rows']='read.rows'
    plans['omitted_filter']=wrong
    for name,obj in [('task',task),('verification_recipe',recipe),*plans.items()]:
        p=directory/(name+'.json');p.write_bytes(canonical(obj));p.chmod(0o600)
    return task,plans,recipe,data


def run_demo(output:Path,*,n=257,k=20):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True,mode=0o700)
    task,plans,recipe,data=prepare_fixture(output/'fixture',n=n,k=k)
    registry=FileRegistry(task,{task['datasets'][0]['id']:data},allowed_root=output)
    reports={}
    for name,plan in plans.items():
        reports[name]=run_f1_reference(task,plan,registry=registry,recipe=recipe,output=output/name,
                                      record_id=name,generation_id='handcrafted-'+name)
    valid=all(reports[n]['terminal_status']=='COMPLETED' and reports[n]['verification']['status']=='PASS' for n in ('streaming_heap','full_sort'))
    same=reports['streaming_heap']['artifact']['content_sha256']==reports['full_sort']['artifact']['content_sha256']
    negative=reports['omitted_filter']['static_status']=='IR_VALIDATED' and reports['omitted_filter']['verification']['status']=='FAIL'
    result={'status':'EXEC001_REFERENCE_DEMO_PASS' if valid and same and negative else 'EXEC001_REFERENCE_DEMO_FAIL',
            'correct_results_identical':same,'wrong_but_static_valid_plan_rejected_by_verifier':negative,
            'cases':{n:{'terminal_status':r['terminal_status'],'verification':r['verification']['status'],
                        'artifact_sha256':r['artifact']['content_sha256'] if r.get('artifact') else None,
                        'node_counters':r['measurements']['node_counters']} for n,r in reports.items()},
            'formal_ready':False,'scope':'ENGINEERING_ONLY','real_model_requests':0}
    (output/'demo_report.json').write_bytes(canonical(result))
    return result
