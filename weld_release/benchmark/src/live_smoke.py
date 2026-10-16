"""Predeclared ten-task integration smoke, not a model leaderboard experiment."""
from common import *
from runtime import Runtime
from transport import OpenRouterClient
MATRIX=['H_G__free','G_WINDOW_2015__free','E_A__free','H_A__free','E_C__free','P_C__free','P_I__free','I_DELAY__all_channels','X05__normal','B_MUSIC__normal']
def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--prefix',default='LIVE_FINAL');a=p.parse_args()
    protocol={'matrix':MATRIX,'model':'google/gemini-3.8-flash','role':'integration smoke, not confirmatory model benchmark','logical_call_cap':40,'manager_turns':10,'worker_turns':8,'output_token_cap':{'manager':8192,'worker':4096},'new_dollar_cap':4.0,'prior_committed_usd':config()['prior_committed_usd'],'auto_retry_unknown':False,'selection':'Two available semantic parents in each of five scenarios; all outcomes retained. Replaces the first smoke instrumentation, which exposed avoidable output duplication and premature termination.','source_hashes':{str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').glob('*.py')}}
    if not (ROOT/f'protocol/{a.prefix}.json').exists():write(ROOT/f'protocol/{a.prefix}.json',protocol)
    if not a.execute:print('Protocol written; --execute authorizes paid admission under existing user cap');return
    client=OpenRouterClient();client.preflight();rows=[]
    for i,tid in enumerate(MATRIX):
        eid=f'{a.prefix}_{i+1:02d}'
        if (ROOT/f'runs/{eid}/summary.json').exists():rows.append(load(ROOT/f'runs/{eid}/summary.json'));continue
        if client.ledger()['fuse'] or client.ledger()['committed_usd']>3.5:break
        print('START',eid,tid,flush=True);rt=Runtime(tid,eid)
        try:
            result=rt.run_agent(client,max_calls=40,manager_turns=10,worker_turns=8);s=load(rt.out/'summary.json');rows.append(s);print('DONE',eid,s['status'],result['success'],s['model_calls'],flush=True)
        finally:rt.close();client.ledger();write(ROOT/f'qa/{a.prefix}_progress.json',rows)
    report={'planned':len(MATRIX),'recorded':len(rows),'evaluated':sum(x['status']=='EVALUATED' for x in rows),'task_successes':sum(x['evaluation']['success'] for x in rows),'episodes':rows,'accounting':client.ledger()};write(ROOT/f'qa/{a.prefix}.json',report)
    print(dump({k:v for k,v in report.items() if k not in ('episodes','accounting')}))
if __name__=='__main__':main()
