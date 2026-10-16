"""Materialize release conditions. Authored perturbations never become new source parents."""
import copy, shutil, sqlite3, hashlib, csv
from common import *
F=Path('D:/Trae_Code/CodexWork/RCWG_DATASET_FINAL_20261013')
P=Path('D:/Trae_Code/CodexWork/RCWG_FIVE_SCENARIO_PILOT_20261012')
N=Path('D:/Trae_Code/CodexWork/RCWG_MECHANISM_V2_20261012')
O=Path('D:/Trae_Code/CodexWork/RCWG_CODE_REVIEW_20261011')
tasks=[]
def normalize(v):
    if isinstance(v,str): return {'v0':'r0','v1':'r1','fixed':'r2'}.get(v,v)
    if isinstance(v,list): return [normalize(x) for x in v]
    if isinstance(v,dict): return {k:normalize(x) for k,x in v.items()}
    return v
def emit(t,g):
    t=normalize(copy.deepcopy(t));g=normalize(copy.deepcopy(g)); tid=t['id']
    for key in ('answer','before_answer'):
        if isinstance(g.get(key),dict) and 'monthly_rows' in g[key]:
            g[key]['monthly_rows']=[{k:v for k,v in row.items() if k not in ('record_id','input_version')} for row in g[key]['monthly_rows']]
    t.setdefault('initial_version','r0');t.setdefault('final_version',t['initial_version'])
    t.setdefault('track','controlled_continuation');t.setdefault('source_status','DERIVED_FROM_PREVIOUSLY_EXPOSED_SOURCE')
    t.setdefault('conditions',{});t.setdefault('handoffs',[])
    t['public_id']='task_'+hashlib.sha256(tid.encode()).hexdigest()[:12]
    t['answer_schema']=g['answer'];t['answer_fields']=list(g['answer'])
    # Schema exposes types, never private values or cardinalities.
    def shape(x):
        if isinstance(x,dict):return {k:shape(v) for k,v in x.items()}
        if isinstance(x,list):return [shape(x[0])] if x else ['item']
        return 'boolean' if isinstance(x,bool) else 'number' if isinstance(x,(int,float)) else 'string'
    t['answer_schema']=shape(g['answer'])
    g.setdefault('before_answer',g['answer'])
    write(ROOT/'tasks'/f'{tid}.json',t);write(ROOT/'private'/f'{tid}.json',g)
    tasks.append(t)
def base(fam,condition):
    p=load(F/f'tasks/{fam}__{condition}/public.json');g=load(F/f'private/{fam}__{condition}.json')
    hp=load(F/f'tasks/{fam}__{condition}/handoff.json')
    if isinstance(hp,dict): hp=hp.get('packets',hp.get('artifacts',[]))
    t={'id':fam+'__'+condition,'family':fam,'scenario':p['scenario'],'parent':p['source_parent'],'cluster':p['source_cluster'],'condition':condition,'task':p['task'],'handoffs':hp,'conditions':{},'initial_version':p.get('current_version','v0'),'final_version':p.get('current_version','v0')}
    if fam=='H_G':t['dataset']='graph';t['query']={'author_id':28651,'year_min':2010,'year_max':2014}
    if fam=='H_A':t['dataset']='financial'
    if fam=='E_A':t['dataset']='debit';t['query']={'year':'2012','currencies':['CZK','EUR']}
    if fam in ('E_C','P_C'):
        t['dataset']='itsdangerous' if fam=='E_C' else 'requests'
        if fam=='P_C':t['initial_version']=t['final_version']='v1'
        ng=load(F/f"private/{t['dataset']}_{t['final_version']}_normative.json")
        g['required_scope']=ng['affected_scope_groups'];g['normative']=ng
        # Scope is an explicit, separately graded output, not inferred from inspected files.
        g['answer']['impacted_entrypoints']=sorted(set(x for group in ng['affected_scope_groups'] for x in (group if isinstance(group,list) else [group])))
    if fam=='P_I':t['dataset']='incident_unit1';t['cut_timestamp']=1705354566
    return t,g
def clone(fam,cond,ext,variant,changes=None):
    t,g=base(fam,cond);t.update(id=ext+'__'+variant,family=ext,condition=variant)
    t['mechanisms']=[ext];t['conditions'].update(changes or {});return t,g
def extensions():
    for v in ('shared','separate'):
        t,g=clone('H_G','complete','X01',v,{'reference_decomposition':v});emit(t,g)
    for v in ('value_change','object_change','unrelated_change'):
        t,g=clone('E_A','grouped','X02',v)
        target=ROOT/f'assets/debit_{v}.sqlite';shutil.copy2(ROOT/'assets/debit.sqlite',target)
        with sqlite3.connect(target) as c:
            if v=='value_change':c.execute("UPDATE yearmonth SET Consumption=Consumption+100 WHERE CustomerID=1673 AND Date='201201'")
            elif v=='object_change':c.execute("UPDATE customers SET Currency='USD' WHERE CustomerID=1673")
            else:c.execute("UPDATE customers SET Currency='EUR' WHERE CustomerID=6")
            c.commit();ans=debit_answer(c)
        g['before_answer']=g['answer'];g['answer']=ans
        t['update']={'trigger_tools':['select','row_lookup'],'asset':'database','target_version':'r1','target_asset':target.name,'notice':{'value_change':'Consumption for customer 1673 in 201201 increases by 100. Other rows are unchanged.','object_change':'Customer 1673 currency is now USD. Recompute eligibility and follow-up scope.','unrelated_change':'Customer 6 currency is now EUR. Other fields and all consumption records are unchanged.'}[v]}
        t['final_version']='r1';emit(t,g)
    for v,ver in [('unrepaired','v0'),('partial','v1'),('repaired','fixed'),('unrelated_file','v1')]:
        t,g=clone('E_C','grouped','X03',v);t['initial_version']=t['final_version']=ver
        ng=load(F/f'private/itsdangerous_{ver}_normative.json');g['normative']=ng;g['required_scope']=ng['affected_scope_groups']
        g['answer']={'verdict':ng['expected_verdict'],'regressions':[{'check_id':k.split('::')[0],'case_id':k.split('::')[1],**x,'input_version':ver} for k,x in ng['case_outcomes'].items() if x['observed']!=x['expected']],'impacted_entrypoints':sorted(set(x for group in ng['affected_scope_groups'] for x in (group if isinstance(group,list) else [group])))}
        t['handoffs']=[];t['task']=t['task'].replace('Current snapshot: v1.','Current snapshot: '+normalize(ver)+'.')
        if v=='unrelated_file':
            shutil.copytree(ROOT/'assets/itsdangerous/v1',ROOT/'assets/itsdangerous/unrelated',dirs_exist_ok=True)
            (ROOT/'assets/itsdangerous/unrelated/RELEASE_NOTE.txt').write_text('Documentation-only revision. API behavior unchanged.\n',encoding='utf-8')
            t['conditions']['snapshot_folder']='unrelated'
        emit(t,g)
    for v in ('all_channels','late_traces','absent_traces'):
        t,g=clone('P_I','correct_control','X04',v);t['handoffs']=[]
        t['conditions']['traces']='available' if v=='all_channels' else 'pending' if v=='late_traces' else 'absent'
        if v=='late_traces':t['update']={'trigger_tools':['metric_summary'],'asset':'traces','target_version':'r1','notice':'Distributed traces are now available.'};t['final_version']='r1'
        if v=='absent_traces':
            for k in ['top_trace_service','trace_ratio']:g['answer'][k]='unsupported'
            g['unsupported_fields']=['top_trace_service','trace_ratio'];t['task']+=' Traces are permanently unavailable. Complete supported fields and mark unavailable fields unsupported.'
        emit(t,g)
    bpublic=load(N/'dataset/B3/normal.json')
    for ext,variants in [('X05',['normal','fail_before','lost_after']),('X06',['all_success','second_write_fails']),('X07',['normal','stale_two_readers'])]:
        for v in variants:
            t={'id':ext+'__'+v,'family':ext,'scenario':'appworld','dataset':'appworld','parent':'B2','cluster':'APPWORLD_DINNER_22cc237','condition':v,'task':bpublic['task'],'conditions':{'fault':v},'native_task_id':'22cc237_1','mechanisms':[ext]}
            g={'answer':{'completion':'state_verified'},'origin':'Native AppWorld final state; augmented exact recipient/amount/multiplicity and protected-record checks.'};emit(t,g)
    for v in ('serial','parallel'):
        t,g=clone('H_G','gap','X08',v,{'scheduler':v,'controlled_delay_seconds':0.02});t['timing_track']='controlled_delay';emit(t,g)
    for v in ('provided','missing'):
        t,g=clone('E_A','grouped','X09',v)
        g['answer']['risk_class']='high' if v=='provided' else 'unsupported'
        t['task']+=' Also report risk_class under the company policy; unsupported requires naming the missing input.'
        if v=='provided':t['policy']={'rule':'high if annual consumption >= 1000000; otherwise low','threshold':1000000}
        else:g['unsupported_fields']=['risk_class']
        emit(t,g)
    for v in ('nonempty','verified_empty','unfinished'):
        t,g=clone('H_G','complete','X10',v);t['handoffs']=[]
        if v=='verified_empty':
            t['query']['year_min']=2099;t['query']['year_max']=2100;t['task']=t['task'].replace('2010–2014','2099–2100');g['answer']={'paper_ids':[],'top_paper':[],'institutions':[],'top_references':[]}
        if v=='unfinished':t['conditions']['first_read_fault']=True
        emit(t,g)
    for fam,c in [('H_G','gap'),('H_A','gap'),('E_C','grouped'),('P_I','single_error')]:
        for v in ('normal','recoverable_read'):
            t,g=clone(fam,c,'X11',fam+'_'+v,{'first_read_fault':v=='recoverable_read'});emit(t,g)
    for v in ('normal','recoverable_read'):
        t={'id':'X11__B_'+v,'family':'X11','scenario':'appworld','dataset':'appworld','parent':'B2','cluster':'APPWORLD_DINNER_22cc237','condition':v,'task':bpublic['task'],'conditions':{'first_read_fault':v=='recoverable_read'},'native_task_id':'22cc237_1'};emit(t,{'answer':{'completion':'state_verified'}})
    for v in ('update_only','update_handoff','update_identity','source_only','source_binding'):
        if v.startswith('update'):
            t=load(ROOT/'tasks/X02__object_change.json');g=load(ROOT/'private/X02__object_change.json')
            if v=='update_only':t['handoffs']=[]
            if v=='update_handoff':t['handoffs']=t['handoffs'][:1];t['conditions']['handoff_gap']=True
            if v=='update_identity':t['handoffs']=base('E_A','wrong_object_memo')[0]['handoffs'];t['conditions']['identity_contamination']=True
        else:
            t,g=base('P_C','copied_error');t['conditions']['interleaved_tests']=v=='source_binding'
        t.update(id='X12__'+v,family='X12',condition=v,mechanisms=['X12',v]);emit(t,g)
def debit_answer(c,year='2012',currencies=('CZK','EUR')):
    i=c.execute('SELECT y.CustomerID FROM yearmonth y JOIN customers c USING(CustomerID) WHERE y.Date LIKE ? AND c.Currency IN ('+','.join('?'*len(currencies))+') GROUP BY y.CustomerID ORDER BY SUM(y.Consumption) DESC,y.CustomerID LIMIT 1',[year+'%',*currencies]).fetchone()[0]
    rows=[{'record_id':f'{i}:{d}','customer_id':i,'month':str(d),'consumption':float(v),'input_version':'r0'} for d,v in c.execute('SELECT Date,Consumption FROM yearmonth WHERE CustomerID=? AND Date LIKE ? ORDER BY Date',[i,year+'%'])]
    return {'selected_customer':i,'monthly_rows':rows}
def main():
    if (ROOT/'dataset_catalog.json').exists():raise SystemExit('Existing dataset is frozen. Use a new release root for rebuilds.')
    for d in ('tasks','private','assets','protocol','qa','reports','deliveries','vendor'): (ROOT/d).mkdir(parents=True,exist_ok=True)
    for p in (F/'assets').iterdir():
        if p.name=='incident_cpu':continue
        if p.is_dir():shutil.copytree(p,ROOT/'assets'/p.name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'),dirs_exist_ok=True)
        else:shutil.copy2(p,ROOT/'assets'/p.name)
    for name in ('metrics.json','operators.json','source_bindings.json','pilot_source_catalog.json','code_source_manifest.json'):
        shutil.copy2(F/'protocol'/name,ROOT/'protocol'/name)
    shutil.copy2(O/'dataset/checks/observe.py',ROOT/'vendor/observe.py')
    for ds,pid in [('itsdangerous','C1'),('requests','C2')]:
        c=load(P/f'private/{pid}_legacy_tasks.json')[0];write(ROOT/f'protocol/{ds}_checks.json',{'family_id':c['family_id'],'public_checks':c['public_checks']})
        for v in ('v0','v1','fixed'):shutil.copy2(F/f'private/{ds}_{v}_normative.json',ROOT/f'private/{ds}_{v}_normative.json')
    shutil.copy2(N/'src/app_native.py',ROOT/'vendor/app_native.py');shutil.copy2(N/'src/app_bridge_v2.py',ROOT/'vendor/app_bridge_v2.py')
    write(ROOT/'environment.json',{'python':str(P/'env/Scripts/python.exe'),'appworld_python':str(P/'appworld_env/Scripts/python.exe'),'appworld_workspace':str(N/'appworld_workspace'),'legacy_root':str(N),'pilot_root':str(P),'code_root':str(O),'prior_committed_usd':15.417794791,'cumulative_cap_usd':20.0})
    catalog=load(F/'dataset_catalog.json')
    for x in catalog['tasks']:
        if x.get('track')=='controlled_continuation':emit(*base(x['family'],x['condition']))
    for fam,cond in [('H_G','complete'),('H_A','complete'),('E_C','grouped'),('E_A','grouped'),('P_I','correct_control'),('P_C','correct_control')]:
        t,g=base(fam,cond);t['id']=fam+'__free';t['condition']='free';t['handoffs']=[];t['track']='free_construction';emit(t,g)
    extensions()
    # Additional semantic parents from the frozen sources, separated from new-source claims.
    for year in ('2011','2013'):
        t,g=base('E_A','grouped');t.update(id='A_YEAR_'+year+'__free',family='A_YEAR',parent='A_YEAR_'+year,condition='free',track='free_construction',handoffs=[])
        t['query']['year']=year;t['task']=t['task'].replace('2012',year)
        with sqlite3.connect(ROOT/'assets/debit.sqlite') as c:g={'answer':debit_answer(c,year),'origin':'New year-specific investigation on the frozen BIRD debit source.'}
        emit(t,g)
    for aid in (28651,):
        for lo,hi in [(2000,2009),(2015,2020)]:
            t,g=base('H_G','complete');t.update(id=f'G_WINDOW_{lo}__free',family='G_WINDOW',parent=f'G_WINDOW_{lo}',condition='free',track='free_construction',handoffs=[])
            t['query'].update(year_min=lo,year_max=hi);t['task']=t['task'].replace('2010–2014',f'{lo}–{hi}')
            with sqlite3.connect(ROOT/'assets/graph.sqlite') as c:
                ids=[r[0] for r in c.execute('SELECT n.id FROM edges e JOIN nodes n ON n.id=e.dst WHERE e.src=? AND e.type=3 AND n.year BETWEEN ? AND ? ORDER BY n.id',(aid,lo,hi))]
                top=c.execute('SELECT n.id,n.citations FROM edges e JOIN nodes n ON n.id=e.dst WHERE e.src=? AND e.type=3 AND n.year BETWEEN ? AND ? ORDER BY n.citations DESC,n.id LIMIT 1',(aid,lo,hi)).fetchall()
                inst=[r[0] for r in c.execute('SELECT DISTINCT i.dst FROM edges a JOIN edges i ON a.src=i.src AND i.type=0 WHERE a.type=3 AND a.dst IN ('+','.join('?'*len(ids))+') ORDER BY i.dst',ids)] if ids else []
                refs=[r[0] for r in c.execute('SELECT dst FROM edges WHERE src=? AND type=1 ORDER BY dst',(top[0][0],))] if top else []
                g={'answer':{'paper_ids':ids,'top_paper':[list(r) for r in top],'institutions':inst,'top_references':refs},'origin':'New window-specific dossier on the same STaRK slice.'}
            emit(t,g)
    for t in tasks:
        # Public views deliberately omit family, treatment, oracle, and source-parent names.
        public={k:t[k] for k in ('public_id','task','scenario','initial_version','answer_schema')}
        public['versions']=['r0','r1','r2'];public['handoffs']=t['handoffs'];public['contract']='Return answer plus claims [{field, value, evidence:[artifact IDs]}]. Code findings may be grouped. All native source tools are available. Report unsupported with missing input for unavailable fields.'
        if t.get('policy'):public['policy']=t['policy']
        write(ROOT/'agent_views'/f"{t['public_id']}.json",public)
    write(ROOT/'dataset_catalog.json',{'version':'2.0','status':'MATERIALIZED','tasks':[{k:t.get(k) for k in ('id','family','scenario','parent','cluster','condition','track','source_status')} for t in tasks],'task_count':len(tasks),'semantic_parents':len(set(t['parent'] for t in tasks)),'source_clusters':len(set(t['cluster'] for t in tasks)),'new_original_sources':0,'held_out_claim':False,'historical_10_cells':'Preserved separately in legacy replay; not advertised as newly implemented cells.'})
    with (ROOT/'task_index.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['id','family','scenario','parent','cluster','condition','track'];w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(tasks)
    print(dump({'tasks':len(tasks),'families':len(set(t['family'] for t in tasks)),'root':str(ROOT)}))
if __name__=='__main__':main()
