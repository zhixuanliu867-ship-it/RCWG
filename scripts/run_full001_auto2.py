"""AUTO2 task-delegation entry point. No manual receipt is synthesized."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rcwg_full.auto2.control import validate_policy
from rcwg_full.auto2.pipeline import Pipeline
from rcwg_full.auto2.remote import RemoteExecutor


def main():
    p=argparse.ArgumentParser();p.add_argument('--policy',type=Path,required=True);p.add_argument('--work-root',type=Path,required=True)
    p.add_argument('--resume',action='store_true');p.add_argument('--through',choices=['live'],required=True);a=p.parse_args()
    policy=validate_policy(json.loads(a.policy.read_text('utf8')))
    config=a.work_root/'RUN_CONFIG.json'
    if not config.is_file():raise PermissionError('PREPARATION_CONFIGURATION_REQUIRED: no cloud defaults or invented account')
    executor=RemoteExecutor(a.work_root)
    pipeline=Pipeline(a.work_root,policy,executor)
    try:
        result=pipeline.run()
    finally:
        pipeline.index.close()
    (a.work_root/'RUN_STATE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'state':result['state'],'reserved_microusd':result['reserved_microusd'],'remaining_microusd':result['remaining_microusd']}))

if __name__=='__main__':main()
