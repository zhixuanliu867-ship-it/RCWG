"""Single release entry point."""
import argparse,sys
from common import *
def main():
    p=argparse.ArgumentParser(description='RCWG five-domain workflow evaluation release')
    sp=p.add_subparsers(dest='cmd',required=True)
    sp.add_parser('list')
    r=sp.add_parser('reference');r.add_argument('task');r.add_argument('--episode',required=True)
    a=sp.add_parser('accept');a.add_argument('--prefix',required=True)
    v=sp.add_parser('evaluate');v.add_argument('episode')
    c=sp.add_parser('compare');c.add_argument('reference');c.add_argument('candidate')
    sp.add_parser('verify')
    args=p.parse_args()
    if args.cmd=='list':
        cat=load(ROOT/'dataset_catalog.json');print(dump({'task_count':cat['task_count'],'tasks':cat['tasks']}))
    elif args.cmd=='reference':
        from references import run
        ev=run(args.task,args.episode);print(dump({'episode':args.episode,'success':ev['success'],'status':ev['status']}))
    elif args.cmd=='accept':
        from acceptance import contracts,runtime_controls
        rows=contracts(args.prefix);checks=runtime_controls(args.prefix);print(dump({'tasks':len(rows),'passed_tasks':sum(x['pass'] for x in rows),'runtime_checks':len(checks),'runtime_passed':sum(x['pass'] for x in checks)}))
        if not all(x['pass'] for x in rows+checks):raise SystemExit(1)
    elif args.cmd=='evaluate':
        from acceptance import read_episode
        from evaluator import evaluate
        summary=load(ROOT/f'runs/{args.episode}/summary.json');s,a,e,n=read_episode(args.episode);ev=evaluate(load(ROOT/f"tasks/{summary['task_id']}.json"),s,a,e,n);write(ROOT/f'recomputed/{args.episode}.json',ev);print(dump(ev))
    elif args.cmd=='compare':
        from metrics import compare
        print(dump(compare(ROOT/'runs'/args.reference,ROOT/'runs'/args.candidate)))
    else:
        manifest=load(ROOT/'manifest.json');bad=[]
        for row in manifest['files']:
            path=ROOT/row['path']
            if not path.exists() or sha(path)!=row['sha256']:bad.append(row['path'])
        print(dump({'checked':len(manifest['files']),'mismatches':bad}));raise SystemExit(bool(bad))
if __name__=='__main__':main()
