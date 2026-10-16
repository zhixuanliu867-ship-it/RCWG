"""Instrument acceptance controllers. Not model observations or competitive baselines.

Graph/SQL are computed from public operators. Code/incident labels use private
fixtures to test the judge while requiring fresh native observations as evidence.
"""
import copy,ast,json,re
from collections import defaultdict
from common import *
from runtime import Runtime
def read(rt,actor,op,args,used):
    for attempt in range(2):
        r=rt.tool(actor,op,args)
        if r.get('artifact_id'):used.append(r['artifact_id'])
        if r['ok']:return r['data']
        if 'RECOVERABLE' not in dump(r) and 'TRANSIENT_WRITE' not in dump(r):break
    raise RuntimeError('tool failed '+op+': '+dump(r))
def pages(rt,actor,op,args,used):
    rows=[];offset=0
    while True:
        r=read(rt,actor,op,{**args,'offset':offset,'limit':1000},used);rows+=r['rows']
        if not r['has_more']:return rows
        offset=r['next_offset']
def graph(rt):
    q=rt.task['query'];used=[]
    def discover(r,t):
        rows=pages(r,'worker:'+t['id'],'neighbors',{'ids':[q['author_id']],'edge_type':3,'direction':'out'},used)
        ps=[x for x in rows if q['year_min']<=(x.get('year') or -1)<=q['year_max']]
        return {'result':{'eligible':ps},'evidence':list(used)}
    rt.edit([{'id':'discover','scope':'Discover eligible authored papers and their record identities','dependencies':[]}]);rt.dispatch(['discover'],discover)
    records=rt.artifacts[rt.results['discover']]['content']['eligible'];ids=sorted({x['dst'] for x in records});rt.event('manager_decision_started',actor='manager')
    separate=rt.task['conditions'].get('reference_decomposition')=='separate';is_timing=rt.task['family']=='X08'
    groups=[[p] for p in ids] if separate else [ids[:len(ids)//2],ids[len(ids)//2:]] if is_timing else [ids]
    taskids=[]
    for i,group in enumerate(groups):
        tid='followup_'+str(i);taskids.append(tid);rt.edit([{'id':tid,'scope':{'paper_ids':group,'goal':'Discover coauthors then their affiliations'},'dependencies':['discover']}],reason_ids=[e['event_id'] for e in rt.events if e['kind']=='worker_finished' and e['task_id']=='discover'])
    def follow(r,t):
        refs=[];group=t['scope']['paper_ids'];authors=set();institutions=set()
        for i in range(0,len(group),100):
            for row in pages(r,'worker:'+t['id'],'neighbors',{'ids':group[i:i+100],'edge_type':3,'direction':'in'},refs):authors.add(row['src'])
        authors=sorted(authors)
        for i in range(0,len(authors),100):
            for row in pages(r,'worker:'+t['id'],'neighbors',{'ids':authors[i:i+100],'edge_type':0,'direction':'out'},refs):institutions.add(row['dst'])
        return {'result':{'institutions':sorted(institutions)},'evidence':refs}
    rt.dispatch(taskids,follow);top=sorted(records,key=lambda x:(-x['citations'],x['dst']))[:1];refs=[]
    rt.edit([{'id':'references','scope':'Read references of the selected top-cited paper','dependencies':['discover']}])
    def readrefs(r,t):
        rr=pages(r,'worker:'+t['id'],'neighbors',{'ids':[top[0]['dst']],'edge_type':1,'direction':'out'},refs) if top else []
        return {'result':{'top_references':sorted({x['dst'] for x in rr})},'evidence':refs}
    rt.dispatch(['references'],readrefs)
    institutions=sorted({i for tid in taskids for i in rt.artifacts[rt.results[tid]]['content']['institutions']})
    return {'paper_ids':ids,'top_paper':[[x['dst'],x['citations']] for x in top],'institutions':institutions,'top_references':rt.artifacts[rt.results['references']]['content']['top_references']}
def analytics(rt):
    used=[]
    def investigate(r,t):
        actor='worker:'+t['id'];read(r,actor,'schema',{},used)
        if r.task['dataset']=='financial':
            rows=pages(r,actor,'select',{'sql':'SELECT l.loan_id,l.account_id,a.district_id,d.A3 AS region,l.amount,l.status FROM loan l JOIN account a USING(account_id) JOIN district d ON d.district_id=a.district_id ORDER BY l.loan_id'},used)
            agg=defaultdict(lambda:[0,0,0]);ids=[];amount=0
            for i,_,_,region,v,status in rows:ids.append(i);amount+=v;agg[region][0]+=1;agg[region][1]+=v;agg[region][2]+=int(status in ('B','D'))
            answer={'loan_ids':ids,'regional':[[k,*v] for k,v in sorted(agg.items())],'total_amount':amount}
        else:
            year=r.task['query']['year'];currencies=r.task['query']['currencies'];quoted=','.join("'"+v+"'" for v in currencies)
            sql=f"SELECT y.CustomerID,SUM(y.Consumption) AS total FROM yearmonth y JOIN customers c USING(CustomerID) WHERE y.Date LIKE '{year}%' AND c.Currency IN ({quoted}) GROUP BY y.CustomerID ORDER BY SUM(y.Consumption) DESC,y.CustomerID LIMIT 1"
            rank=read(r,actor,'select',{'sql':sql},used)
            if r.update_notice:
                r.event('manager_decision_started',actor='manager');rank=read(r,actor,'select',{'sql':sql},used)
            selected=rank['rows'][0][0];monthly=read(r,actor,'select',{'sql':f"SELECT CustomerID,Date,Consumption FROM yearmonth WHERE CustomerID={selected} AND Date LIKE '{year}%' ORDER BY Date"},used)
            answer={'selected_customer':selected,'monthly_rows':[{'customer_id':i,'month':str(d),'consumption':float(v)} for i,d,v in monthly['rows']]}
            if 'risk_class' in r.task['answer_fields']:answer['risk_class']=('high' if sum(x['consumption'] for x in answer['monthly_rows'])>=r.task['policy']['threshold'] else 'low') if r.task.get('policy') else 'unsupported'
        return {'result':{'answer':answer},'evidence':used}
    rt.edit([{'id':'audit','scope':'Reconcile source rows and aggregates, then investigate the selected object','dependencies':[]}]);rt.dispatch(['audit'],investigate)
    return rt.artifacts[rt.results['audit']]['content']['answer']
def code_review(rt):
    g=load(ROOT/f"private/{rt.task['id']}.json");used=[]
    def investigate(r,t):
        a='worker:'+t['id'];read(r,a,'list_files',{},used);read(r,a,'read_file',{'path':'REVIEW_CONTEXT.md','lines':1000},used)
        start=1
        while True:
            p=read(r,a,'read_probe_inputs',{'start':start,'lines':1000},used)
            if start+len(p['lines'])>p['total_lines']:break
            start+=len(p['lines'])
        for path in g['answer']['impacted_entrypoints']:read(r,a,'read_file',{'path':path,'lines':1000},used)
        checks=read(r,a,'run_checks',{},used)['available_checks'];read(r,a,'run_checks',{'check_names':[x['name'] for x in checks]},used)
        return {'result':{'answer':g['answer']},'evidence':used}
    rt.edit([{'id':'review','scope':'Execute public checks, inspect normative input contract and impacted entrypoints','dependencies':[]}]);rt.dispatch(['review'],investigate)
    return g['answer']
def incident(rt):
    g=load(ROOT/f"private/{rt.task['id']}.json");used=[]
    def investigate(r,t):
        a='worker:'+t['id'];read(r,a,'metric_summary',{'filter':'cpu'},used);read(r,a,'metric_summary',{'filter':'latency-90'},used);read(r,a,'log_search',{'regex':'error|fail|timeout'},used)
        if r.adapter.trace_state=='available':read(r,a,'trace_summary',{},used)
        r.event('manager_decision_started',actor='manager')
        return {'result':{'answer':g['answer']},'evidence':used}
    rt.edit([{'id':'diagnose','scope':'Compare signals across channels and distinguish observed statistics from diagnosis','dependencies':[]}]);rt.dispatch(['diagnose'],investigate);answer=copy.deepcopy(g['answer']);answer['explanation']='The CPU increase in checkoutservice supports the CPU-root hypothesis, while the largest latency-90 ratio is at paymentservice. A downstream symptom can differ from the root because service dependencies may propagate delay; these summaries do not prove that specific causal path. Zero matches for error|fail|timeout only describes the searched available log messages, not the absence of errors.';return answer
def parse_app(data):
    s=data['output'].strip()
    if s.startswith('Execution failed'):raise RuntimeError(s)
    try:return json.loads(s)
    except ValueError:
        try:return ast.literal_eval(s)
        except (ValueError,SyntaxError):return s
def appworld(rt, preferred_playlist_id=None):
    used=[]
    def app(a,api,args=None):return parse_app(read(rt,'worker:reconcile','app_call',{'app':a,'api':api,'arguments':args or {}},used))
    def allpages(a,api,args):
        rows=[]
        for page in range(20):
            x=app(a,api,{**args,'page_index':page})
            if not isinstance(x,list):raise RuntimeError('Unexpected paginated response '+str(x)[:300])
            rows+=x
            if not x:break
        return rows
    def investigate(r,t):
        if r.task.get('native_task_id')=='b0a8eae_1':
            from datetime import datetime
            notes=allpages('simple_note','search_notes',{'query':'workout'});note=next(x for x in notes if any(y in x['title'].lower() for y in ('workout','exercise')));content=app('simple_note','show_note',{'note_id':note['note_id']})['content']
            day=datetime.fromisoformat(r.task['datetime']).strftime('%A').lower();duration=next(int(p.splitlines()[-1].split('duration_mins: ')[-1].strip()) for p in content.split('\n\n') if p.splitlines()[0].split('day: ')[-1].strip().lower()==day)
            playlists=allpages('spotify','show_playlist_library',{})
            if preferred_playlist_id is not None:playlists.sort(key=lambda p:p['playlist_id']!=preferred_playlist_id)
            for playlist in playlists:
                total=sum(app('spotify','show_song',{'song_id':sid})['duration'] for sid in playlist['song_ids'])
                if total>=60*duration:app('spotify','play_music',{'playlist_id':playlist['playlist_id']});break
            else:raise RuntimeError('No eligible playlist')
            app('supervisor','complete_task',{'status':'success'});return {'result':{'answer':{'completion':'state_verified'}},'evidence':used}
        contacts=allpages('phone','search_contacts',{'query':'coworker','relationship':'coworker'});notes=allpages('simple_note','search_notes',{'query':'Work Dinner'})
        note=next(x for x in notes if x['created_at']>='2023-05-19');content=app('simple_note','show_note',{'note_id':note['note_id']})['content'];shares={}
        for line in content.splitlines():
            if line.strip().startswith('-'):
                name,amount=line.strip()[1:].split('=>');shares[name.strip()]=float(amount.strip().replace('$',''))
        emails={x['first_name']:x['email'] for x in contacts};pending={emails[n]:v for n,v in shares.items()}
        trans=allpages('venmo','show_transactions',{'direction':'received','sort_by':'-created_at','min_created_at':'2023-05-19'})
        for x in trans:
            if x['description']=='Work Dinner':pending.pop(x['sender']['email'],None)
        for email,amount in pending.items():
            def existing():
                rows=allpages('venmo','show_sent_payment_requests',{})
                return any(x.get('receiver',{}).get('email')==email and abs(x.get('amount',-100)-amount)<.005 and x.get('description')=='Work Dinner' for x in rows)
            if existing():continue
            result=read(r,'worker:reconcile','app_call',{'app':'venmo','api':'create_payment_request','arguments':{'user_email':email,'amount':amount,'description':'Work Dinner'}},used)
            if result.get('withheld') and not existing():raise RuntimeError('Uncertain commit was not reconciled')
        app('supervisor','complete_task',{'status':'success'});return {'result':{'answer':{'completion':'state_verified'}},'evidence':used}
    deps=[]
    if rt.task['conditions'].get('fault')=='stale_two_readers':
        rt.edit([{'id':k,'scope':'Read initial payment requests before concurrent writes','dependencies':[]} for k in ('reader_a','reader_b')])
        def reader(r,t):
            refs=[];x=read(r,'worker:'+t['id'],'app_call',{'app':'venmo','api':'show_sent_payment_requests','arguments':{}},refs);return {'result':x,'evidence':refs}
        rt.dispatch(['reader_a','reader_b'],reader);deps=['reader_a','reader_b'];rt.event('interleaving_checkpoint',schedule='reader_a, reader_b, reconcile, state_refresh, remaining_writes')
    rt.edit([{'id':'reconcile','scope':'Discover dinner shares, prior transfers and pending recipients; reconcile writes','dependencies':deps}]);rt.dispatch(['reconcile'],investigate)
    if 'reconcile' not in rt.results:raise RuntimeError('AppWorld acceptance controller failed')
    return {'completion':'state_verified'}
def run(task_id,episode_id):
    rt=Runtime(task_id,episode_id);rt.event('acceptance_controller',controller='SCRIPTED_INSTRUMENT_CONTROL',uses_private_labels=rt.task['scenario'] in ('code_review','incident'));rt.seed_handoffs()
    try:
        answer=globals()[rt.task['scenario']](rt);evidence=list(rt.results.values());claims=[{'field':k,'value':v,'evidence':evidence} for k,v in answer.items()]
        rt.submit({'answer':answer,'claims':claims,'evidence':evidence});result=rt.finish();return result
    finally:rt.close()
if __name__=='__main__':
    import sys
    print(dump(run(sys.argv[1],sys.argv[2])))
