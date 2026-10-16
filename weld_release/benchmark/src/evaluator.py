"""Task contracts, typed evidence, semantic versions and adjudication are separate outputs."""
import copy, re
from collections import Counter
from common import *
def normalize_submission(s):
    if not isinstance(s,dict):return None
    s=copy.deepcopy(s);a=s.get('answer',s.get('answers'))
    if a is None:a={k:v for k,v in s.items() if k not in ('claims','evidence','findings','inspected_files','defect_files')}
    if not isinstance(a,dict):return None
    aliases={'snapshot':'input_version','case':'case_id','check':'check_id','observed_outcome':'observed','expected_outcome':'expected','customerId':'customer_id','CustomerID':'customer_id','YYYYMM':'month','Date':'month','Consumption':'consumption'}
    def norm(x):
        if isinstance(x,list):return [norm(y) for y in x]
        if isinstance(x,dict):return {aliases.get(k,k):norm(v) for k,v in x.items()}
        return {'v0':'r0','v1':'r1','fixed':'r2'}.get(x,x) if isinstance(x,str) else x
    a=norm(a)
    if isinstance(a.get('monthly_rows'),list):
        a['monthly_rows']=[{k:v for k,v in row.items() if k not in ('record_id','input_version')} if isinstance(row,dict) else row for row in a['monthly_rows']]
    if 'findings' in s or 'findings' in a:
        findings=s.get('findings',a.pop('findings',[]));cases=[]
        if not isinstance(findings,list) or any(not isinstance(f,dict) for f in findings):return None
        for f in findings:
            cs=f.get('cases',f.get('behavioral_claims',f.get('regressions',[])))
            if not isinstance(cs,list):return None
            cases.extend(norm(x) for x in cs)
        a['regressions']=cases
    def regression_rows(value):
        if not isinstance(value,list):return value
        keys=('input_version','check_id','case_id','observed','expected')
        return [dict(zip(keys,norm(row))) if isinstance(row,list) and len(row)==5 and all(isinstance(x,str) for x in row) else row for row in value]
    if 'regressions' in a:a['regressions']=regression_rows(a['regressions'])
    for claim in s.get('claims',[]) if isinstance(s.get('claims'),list) else []:
        if isinstance(claim,dict) and claim.get('field')=='regressions' and 'value' in claim:claim['value']=regression_rows(norm(claim['value']))
    def verdict(v):
        if not isinstance(v,str):return v
        aliases=load(ROOT/'qa/verdict_semantic_aliases.json') if (ROOT/'qa/verdict_semantic_aliases.json').exists() else {}
        if v in aliases:return aliases[v]['canonical']
        key=v.strip().lower()
        return 'approve' if key in ('pass','accept','accepted','approved','approve') else 'request_changes' if key in ('fail','reject','rejected','request_changes','changes_requested','regressions_found') else v
    if 'verdict' in a:a['verdict']=verdict(a['verdict'])
    for c in s.get('claims',[]) if isinstance(s.get('claims',[]),list) else []:
        if isinstance(c,dict) and c.get('field')=='verdict' and 'value' in c:c['value']=verdict(c['value'])
    s['answer']=a;return s
def ancestors(ids,artifacts):
    found={};missing=[];stack=list(ids);visiting=set()
    while stack:
        i=stack.pop()
        if not isinstance(i,str) or i not in artifacts:missing.append(str(i));continue
        if i in found:continue
        found[i]=artifacts[i];stack.extend(artifacts[i].get('input_refs',[]))
    return found,missing
def observed(ids,artifacts,events):
    found,missing=ancestors(ids,artifacts);es={e['event_id']:e for e in events};good=[]
    for a in found.values():
        e=es.get(a.get('producer_event_id'))
        if not e or a['content_hash']!=hashlib.sha256(dump(a['content']).encode()).hexdigest():missing.append(a['artifact_id']);continue
        if a.get('kind')=='observation' and e['kind']=='tool_completed' and e['status']=='OK' and a['content'].get('ok'):
            if a['content'].get('operation')!=e.get('tool') or a['content'].get('arguments')!=e.get('arguments') or a['input_versions']!=e['input_versions']:missing.append(a['artifact_id']);continue
            good.append(a)
    return good,missing,found
import hashlib
def graph_answer(observations,task):
    rows=[];author_complete=False;author=task['query']['author_id'];lo=task['query']['year_min'];hi=task['query']['year_max'];auth_pages=[]
    for art in observations:
        c=art['content'];data=c.get('data',{})
        if isinstance(data,dict):rows.extend(data.get('rows',[]))
        args=c.get('arguments',{})
        if c.get('operation')=='neighbors' and args.get('ids')==[author] and args.get('edge_type')==3 and args.get('direction','out')=='out':auth_pages.append((args.get('offset',0),len(data.get('rows',[])),data.get('has_more')))
    offset=0
    for start,n,more in sorted(set(auth_pages)):
        if start==offset:
            offset+=n
            if more is False:author_complete=True;break
    papers={r['dst']:r for r in rows if isinstance(r,dict) and r.get('src')==author and r.get('type')==3 and lo<=(r.get('year') or -1)<=hi}
    top=sorted(papers.values(),key=lambda r:(-(r.get('citations') or 0),r['dst']))[:1]
    authors={r['src'] for r in rows if isinstance(r,dict) and r.get('type')==3 and r.get('dst') in papers}
    inst=sorted({r['dst'] for r in rows if isinstance(r,dict) and r.get('type')==0 and r.get('src') in authors})
    refs=sorted({r['dst'] for r in rows if isinstance(r,dict) and r.get('type')==1 and top and r.get('src')==top[0]['dst']})
    return {'paper_ids':sorted(papers),'top_paper':[[r['dst'],r['citations']] for r in top],'institutions':inst,'top_references':refs},author_complete
def evidence_support(task,gold,answer,observations,native,context=None):
    support={k:False for k in gold['answer']};detail={};scenario=task['scenario'];cur=task['final_version']
    usable=[]
    for art in observations:
        c=art['content'];v=art['input_versions']['source'];usable.append((c,v))
    if scenario=='graph':
        derived,complete=graph_answer(observations,task)
        for k in support:support[k]=complete and equal(answer.get(k),derived.get(k),k)
        if context is not None:
            full,full_complete=graph_answer(context,task);rows=[r for a in observations for r in a['content'].get('data',{}).get('rows',[]) if isinstance(r,dict)]
            eligible=set(full['paper_ids']);coauthors={r['src'] for a in context for r in a['content'].get('data',{}).get('rows',[]) if isinstance(r,dict) and r.get('type')==3 and r.get('dst') in eligible}
            affiliations=sorted({r['dst'] for r in rows if r.get('type')==0 and r.get('src') in coauthors})
            top=full['top_paper'][0][0] if full['top_paper'] else None;references=sorted({r['dst'] for r in rows if r.get('type')==1 and r.get('src')==top})
            support['institutions']=full_complete and equal(answer.get('institutions'),affiliations,'institutions')
            support['top_references']=full_complete and equal(answer.get('top_references'),references,'top_references')
        detail['exhaustive_authorship_read']=complete
    elif scenario=='analytics':
        records=[];querydata=[]
        for c,v in usable:
            d=c.get('data',{})
            if c.get('operation') not in ('select','row_lookup') or not isinstance(d,dict) or not d.get('read_tables'):continue
            ds=[dict(zip(d['columns'],r)) for r in d.get('rows',[])]
            # A key fixed by an unambiguous conjunction is part of query identity;
            # requiring it again in SELECT would reject equivalent decompositions.
            sql=d.get('sql','');where=re.split(r'\bwhere\b',sql,flags=re.I)[-1]
            fixed=re.search(r'(?i)(?:\b\w+\.)?["`\[]?CustomerID["`\]]?\s*=\s*[\'\"]?(\d+)[\'\"]?(?=\s|$|\))',where) if re.search(r'(?i)\bwhere\b',sql) and not re.search(r'(?i)\bor\b|\bunion\b',sql) else None
            for row in ds:
                row.update({{'customer_id':'CustomerID','month':'Date','consumption':'Consumption'}.get(k,k):val for k,val in list(row.items())})
                if fixed and not any(k.lower()=='customerid' for k in row):row['CustomerID']=int(fixed.group(1))
            records.extend((r,v) for r in ds);querydata.append((d,v))
        def applicable(k,v):return v==cur or equal(gold.get('before_answer',{}).get(k),gold['answer'][k],k)
        if task['dataset']=='debit':
            selected=answer.get('selected_customer');monthly=answer.get('monthly_rows',[])
            for d,v in querydata:
                names=[{'customer_id':'customerid'}.get(x.lower(),x.lower()) for x in d['columns']];sql=d['sql'].lower()
                if applicable('selected_customer',v) and 'customers' in d['read_tables'] and 'yearmonth' in d['read_tables'] and 'sum(' in sql.replace(' ','') and 'group by' in sql and 'order by' in sql and d['rows'] and 'customerid' in names:
                    support['selected_customer'] |= d['rows'][0][names.index('customerid')]==selected
            seen={}
            for r,v in records:
                row={k.lower():x for k,x in r.items()}
                if all(k in row for k in ('customerid','date','consumption')):seen[(row['customerid'],str(row['date']),v)]=row['consumption']
            monthly_valid=isinstance(monthly,list) and bool(monthly) and all(isinstance(x,dict) and type(x.get('customer_id')) in (str,int) and isinstance(x.get('month'),str) and type(x.get('consumption')) in (int,float) for x in monthly)
            support['monthly_rows']=monthly_valid and all(any((x.get('customer_id'),x.get('month'),v) in seen and applicable('monthly_rows',v) and equal(x.get('consumption'),seen[(x.get('customer_id'),x.get('month'),v)],'consumption') for v in ('r0','r1','r2')) for x in monthly if isinstance(x,dict)) and all(isinstance(x,dict) for x in monthly)
            if 'risk_class' in support:
                if task.get('policy'):support['risk_class']=support['monthly_rows'] and answer.get('risk_class')==('high' if sum(x['consumption'] for x in monthly)>=task['policy']['threshold'] else 'low')
                else:support['risk_class']=answer.get('risk_class')=='unsupported'
        else:
            raw=[r for r,v in records if all(k in r for k in ('loan_id','region','amount','status'))]
            dedup={r['loan_id']:r for r in raw};regions={}
            for r in dedup.values():
                z=regions.setdefault(r['region'],[0,0,0]);z[0]+=1;z[1]+=r['amount'];z[2]+=int(r['status'] in ('B','D'))
            derived={'loan_ids':sorted(dedup),'regional':[[k,*x] for k,x in sorted(regions.items())],'total_amount':sum(r['amount'] for r in dedup.values())}
            for k in support:support[k]=bool(raw) and equal(answer.get(k),derived[k],k)
            # Aggregate-only SQL is admitted when its observed result has the required keys and values.
            for d,v in querydata:
                if {'loan','account','district'}<=set(d['read_tables']):
                    if 'regional' in support and equal(answer.get('regional'),d['rows'],'regional'):support['regional']=True
                if set(d['columns'])=={'loan_id'} and equal(answer.get('loan_ids'),[x[0] for x in d['rows']],'loan_ids') and not d['has_more']:support['loan_ids']=True
                if 'loan' in d['read_tables'] and len(d['rows'])==1 and len(d['rows'][0])==1 and equal(answer.get('total_amount'),d['rows'][0][0],'total_amount'):support['total_amount']=True
            # Additional selected columns do not remove the information in a
            # named projection. Require complete observed rows and unambiguous names.
            loan_values={};loan_conflict=False
            for d,v in querydata:
                columns=d['columns']
                if d.get('has_more') or len(set(columns))!=len(columns):continue
                ix={name:i for i,name in enumerate(columns)}
                if {'loan','account','district'}<=set(d['read_tables']) and {'region','loan_count','total_amount','adverse_count'}<=set(ix):
                    projected=[[row[ix[k]] for k in ('region','loan_count','total_amount','adverse_count')] for row in d['rows']]
                    if equal(answer.get('regional'),projected,'regional'):support['regional']=True
                if 'loan' in d['read_tables'] and 'loan_id' in ix:
                    ids=[row[ix['loan_id']] for row in d['rows']]
                    if equal(answer.get('loan_ids'),ids,'loan_ids'):support['loan_ids']=True
                    if 'amount' in ix:
                        for row in d['rows']:
                            key,amount=row[ix['loan_id']],row[ix['amount']]
                            if type(key) not in (int,str) or type(amount) not in (int,float):loan_conflict=True;continue
                            if key in loan_values and loan_values[key]!=amount:loan_conflict=True
                            loan_values[key]=amount
            if loan_values and not loan_conflict and equal(answer.get('loan_ids'),list(loan_values),'loan_ids') and equal(answer.get('total_amount'),sum(loan_values.values()),'total_amount'):
                support['total_amount']=True
    elif scenario=='code_review':
        cases={};readpaths=set();input_seen=False;context_seen=False
        for c,v in usable:
            if v!=cur:continue
            d=c['data']
            if c['operation']=='run_checks':
                for check in d.get('checks',[]):
                    for case in check.get('observations',[]):cases[(check['check'],case['case_id'])]=case['observed_outcome']
            if c['operation'] in ('read_file','read_probe_inputs'):
                readpaths.add(d['path']);input_seen|=d['path']=='REGISTERED_CHECKS.py';context_seen|=d['path']=='REVIEW_CONTEXT.md'
        if context is not None:
            for art in context:
                c=art['content']
                if art['input_versions']['source']==cur and c['operation'] in ('read_file','read_probe_inputs'):
                    input_seen|=c['data']['path']=='REGISTERED_CHECKS.py';context_seen|=c['data']['path']=='REVIEW_CONTEXT.md'
        regs=answer.get('regressions',[])
        regs_valid=isinstance(regs,list) and all(isinstance(r,dict) and all(isinstance(r.get(k),str) for k in ('input_version','check_id','case_id','observed','expected')) for r in regs)
        support['regressions']=regs_valid and all(cases.get((r.get('check_id'),r.get('case_id')))==r.get('observed') and gold['normative']['case_outcomes'].get(r.get('check_id','')+'::'+r.get('case_id',''),{}).get('expected')==r.get('expected') and r.get('input_version')==cur and context_seen and input_seen for r in regs)
        # A clean verdict requires actual current checks, not an empty list with no investigation.
        support['verdict']=bool(cases) and context_seen and support['regressions']
        if context is not None and readpaths:
            global_cases={}
            for art in context:
                c=art['content']
                if art['input_versions']['source']==cur and c['operation']=='run_checks':
                    for ch in c['data'].get('checks',[]):
                        for case in ch.get('observations',[]):global_cases[(ch['check'],case['case_id'])]=case['observed_outcome']
            support['verdict']=regs_valid and bool(global_cases) and context_seen and input_seen and all(global_cases.get((r.get('check_id'),r.get('case_id')))==r.get('observed') and gold['normative']['case_outcomes'].get(r.get('check_id','')+'::'+r.get('case_id',''),{}).get('expected')==r.get('expected') for r in regs)
        from impact import check as impact_check
        impact_ok,impact_detail=impact_check(answer.get('impacted_entrypoints',[]),task,gold)
        support['impacted_entrypoints']=impact_ok and all(any(p in readpaths for p in group) for group in gold.get('required_scope',[]))
        if context is not None and any(p.startswith('src/') for p in readpaths):
            global_paths={art['content']['data']['path'] for art in context if art['input_versions']['source']==cur and art['content']['operation'] in ('read_file','read_probe_inputs')}
            support['impacted_entrypoints']=impact_ok and all(any(p in global_paths for p in group) for group in gold.get('required_scope',[]))
        detail['impact_resolution']=impact_detail
        detail.update(current_native_cases=len(cases),context_read=context_seen,probe_inputs_read=input_seen,inspected_files=sorted(readpaths))
    elif scenario=='incident':
        metric=[];trace=[];logs=[]
        for c,v in usable:
            if c['operation']=='metric_summary':metric+=c['data']['rows']
            if c['operation']=='trace_summary':trace+=c['data']
            if c['operation']=='log_search':logs.append(c['data'])
        cpu=sorted([r for r in metric if r['metric'].endswith('_cpu')],key=lambda x:-(x['ratio'] or 0));lat=sorted([r for r in metric if 'latency-90' in r['metric']],key=lambda x:-(x['ratio'] or 0));tr=sorted(trace,key=lambda x:-(x['ratio'] or 0))
        derived={}
        if cpu:derived.update(top_cpu_metric=cpu[0]['metric'],cpu_ratio=cpu[0]['ratio'])
        if lat:derived.update(top_p90_metric=lat[0]['metric'],p90_ratio=lat[0]['ratio'])
        if tr:derived.update(top_trace_service=tr[0]['service'],trace_ratio=tr[0]['ratio'])
        if logs:derived['log_keyword_matches']=logs[-1]['count']
        for k in support:
            if k in derived:support[k]=equal(answer.get(k),derived[k],k)
            if k in gold.get('unsupported_fields',[]):support[k]=answer.get(k)=='unsupported'
        # Evidence adequacy for a diagnosis is separate from causal entailment.
        if 'root_service' in gold['answer']:support['root_service']=bool(cpu or tr) and bool(logs) and answer.get('root_service')==gold['answer']['root_service']
        if 'fault_type' in gold['answer']:support['fault_type']=bool(cpu or tr) and answer.get('fault_type')==gold['answer']['fault_type']
        detail['causal_entailment']='ADJUDICATION_NEEDED';detail['diagnosis_support_rule']='Factual injection match plus observed metrics/traces and logs; does not establish causal explanation entailment.'
    else:
        support['completion']=bool(native and native.get('success')) and any(c['operation']=='app_call' for c,v in usable)
    return support,detail
def evaluate_core(task,submission,artifacts,events,native=None):
    g=load(ROOT/f"private/{task['id']}.json");s=normalize_submission(submission)
    if s is None:return {'success':False,'parser_valid':False,'status':'NO_SUBMISSION' if submission is None else 'INVALID_PROTOCOL','factual_correct':False,'task_contract_valid':False,'evidence_valid':False,'field_checks':{},'support_checks':{},'native':native,'answer':{}}
    expected=g['answer'];normalizations=[]
    # Only reversible shape conversions defined by the public field semantics.
    # No values, missing members, ordering choices or evidence are supplied here.
    def shape(value,field,path):
        original=copy.deepcopy(value)
        scalar=lambda x:type(x) in (int,float,str)
        if field in ('paper_ids','institutions','top_references','loan_ids') and isinstance(value,list):
            if len(value)==1 and isinstance(value[0],list) and all(scalar(x) for x in value[0]):value=value[0]
            elif value and all(isinstance(x,list) and len(x)==1 and scalar(x[0]) for x in value):value=[x[0] for x in value]
        if field=='top_paper' and isinstance(value,list):
            if len(value)==2 and all(scalar(x) for x in value):value=[value]
            def paper_row(row):
                if isinstance(row,dict):
                    for first in ('id','paper_id'):
                        for second in ('citations','citation_count'):
                            if set(row)=={first,second}:return [row[first],row[second]]
                return row
            value=[paper_row(x) for x in value]
        if field=='regional' and isinstance(value,list):
            keys=('region','loan_count','total_amount','adverse_count')
            value=[[row[k] for k in keys] if isinstance(row,dict) and set(row)==set(keys) else row for row in value]
        if value!=original:normalizations.append({'path':path,'kind':'public_semantic_shape','original':original,'canonical':copy.deepcopy(value)})
        return value
    s['answer']={k:shape(v,k,'answer.'+k) for k,v in s['answer'].items()}
    for claim in s.get('claims',[]) if isinstance(s.get('claims'),list) else []:
        if isinstance(claim,dict) and isinstance(claim.get('field'),str) and 'value' in claim:
            claim['value']=shape(claim['value'],claim['field'],'claim.'+claim['field'])
    malformed=[k for k,v in expected.items() if k in s['answer'] and isinstance(v,(list,dict)) and not isinstance(s['answer'][k],type(v))]
    if malformed or not isinstance(s.get('claims',[]),list):
        return {'success':False,'parser_valid':True,'status':'INVALID_PROTOCOL','factual_correct':False,'task_contract_valid':False,'evidence_valid':False,'field_checks':{k:False for k in expected},'support_checks':{k:False for k in expected},'native':native,'answer':{},'malformed_fields':malformed}
    def typed(value,template,path):
        if isinstance(template,(int,float)) and not isinstance(template,bool) and isinstance(value,str) and re.fullmatch(r'-?(?:0|[1-9]\d*)(?:\.\d+)?',value):
            if type(template) is int and '.' in value:return value
            parsed=int(value) if type(template) is int else float(value)
            if not math.isfinite(parsed):return value
            normalizations.append({'path':path,'kind':'unambiguous_numeric_string','original':value});return parsed
        if isinstance(template,dict) and isinstance(value,dict):return {k:typed(v,template[k],path+'.'+k) if k in template else v for k,v in value.items()}
        if isinstance(template,list) and isinstance(value,list) and template:
            if isinstance(template[0],(dict,list)):return [typed(v,template[0],path+'[]') for v in value]
            if any(type(x)!=type(template[0]) for x in template):return [typed(v,template[i],path+'['+str(i)+']') if i<len(template) else v for i,v in enumerate(value)]
            return [typed(v,template[0],path+'[]') for v in value]
        return value
    answer=typed(s['answer'],expected,'answer');checks={k:equal(answer.get(k),v,k) for k,v in expected.items()}
    if task['scenario']=='code_review':
        from impact import check as impact_check
        checks['impacted_entrypoints']=impact_check(answer.get('impacted_entrypoints',[]),task,g)[0]
    if task['scenario']=='appworld':
        checks['completion']=bool(isinstance(answer.get('completion'),str) and answer['completion'].strip()) and bool(native and native.get('success'))
        normalizations.append({'path':'answer.completion','kind':'administrative_summary_graded_by_native_state','prose_fact_entailment':'Not scored; additional explicit factual claims require separate verification.'})
    extra=set(answer)-set(expected);claims=s.get('claims',[]);refs=s.get('evidence',[])
    if isinstance(claims,list):
        for c in claims:
            if isinstance(c,dict) and 'value' not in c and isinstance(c.get('field'),str) and c.get('field') in answer:c['value']=copy.deepcopy(answer[c['field']])
    if not isinstance(refs,list):refs=[]
    for c in claims if isinstance(claims,list) else []:
        if isinstance(c,dict) and isinstance(c.get('evidence'),list):refs.extend(c['evidence'])
    obs,missing,found=observed(refs,artifacts,events);support,detail=evidence_support(task,g,answer,obs,native);detail['normalizations']=normalizations
    perclaim=[]
    for claim in claims if isinstance(claims,list) else []:
        if not isinstance(claim,dict):perclaim.append({'status':'INVALID_PROTOCOL'});continue
        k=claim.get('field')
        if not isinstance(k,str) or not isinstance(claim.get('evidence',[]),list):perclaim.append({'status':'INVALID_PROTOCOL','factual':False,'support':False});continue
        co,mi,_=observed(claim.get('evidence',[]),artifacts,events)
        if k not in expected:perclaim.append({'field':k,'status':'ADJUDICATION_NEEDED','reason':'Unregistered claim requires review'});continue
        claim['value']=typed(claim.get('value'),expected[k],'claim.'+k)
        cs,_=evidence_support(task,g,{k:claim.get('value'),**{x:answer.get(x) for x in answer if x!=k}},co,native,context=obs)
        factual=checks['completion'] if task['scenario']=='appworld' and k=='completion' else impact_check(claim.get('value'),task,g)[0] if task['scenario']=='code_review' and k=='impacted_entrypoints' else equal(claim.get('value'),expected[k],k)
        perclaim.append({'field':k,'factual':factual,'support':bool(cs.get(k)) and not mi,'status':'JUDGED'})
    unknown=[]
    if task['scenario']=='code_review':
        allowed={(k.split('::')[0],k.split('::')[1]) for k in g['normative']['case_outcomes']}
        unknown=[r for r in answer.get('regressions',[]) if isinstance(r,dict) and (not isinstance(r.get('check_id'),str) or not isinstance(r.get('case_id'),str) or (r.get('check_id'),r.get('case_id')) not in allowed)]
    supported=all(support.get(k,False) for k in expected) and not missing and bool(obs)
    contradictions=any(x.get('factual') is False or x.get('support') is False for x in perclaim)
    pending=bool(unknown or extra or any(x.get('status')=='ADJUDICATION_NEEDED' for x in perclaim) or s.get('causal_explanation'))
    factual=all(checks.values());scope=True
    if 'impacted_entrypoints' in expected:scope=checks['impacted_entrypoints']
    deadline=task.get('deadline_seconds');end=max((e['monotonic_end'] for e in events),default=0)
    success=factual and supported and scope and not contradictions and not pending
    return {'success':success,'parser_valid':True,'status':'ADJUDICATION_NEEDED' if pending else 'EVALUATED','factual_correct':factual,'task_contract_valid':factual and scope and not pending and not contradictions,'evidence_valid':supported and not contradictions,'deadline_met':end<=deadline if deadline is not None else None,'field_checks':checks,'support_checks':support,'claim_checks':perclaim,'missing_evidence':missing,'extra_answer_fields':sorted(extra),'unregistered_findings':unknown,'evidence_detail':detail,'native':native,'separate_scopes':{'inspected_files':detail.get('inspected_files',[]),'defect_files':s.get('defect_files',[]),'impacted_entrypoints':answer.get('impacted_entrypoints',[])},'observed_artifacts':len(obs),'answer':answer}


def claim_review_key(task,claim,artifacts):
    closure,_=ancestors(claim.get('evidence',[]),artifacts)
    return hashlib.sha256(dump({'task':task['id'],'claim':claim,'ancestor_hashes':{k:v['content_hash'] for k,v in sorted(closure.items())}}).encode()).hexdigest()

def evaluate(task,submission,artifacts,events,native=None):
    from repair_contracts import evaluate_repaired
    s=copy.deepcopy(submission);decided=[];abstention_normalizations=[];outcome_normalizations=[]
    outcome_path=ROOT/'qa/outcome_semantic_aliases.json'
    outcome_aliases=load(outcome_path).get('aliases',{}) if outcome_path.exists() else {}
    def normalize_outcomes(value):
        if isinstance(value,dict):
            if 'check_id' in value and 'case_id' in value:
                for field in ('observed','expected'):
                    old=value.get(field)
                    if isinstance(old,str) and old in outcome_aliases:
                        value[field]=outcome_aliases[old];outcome_normalizations.append({'check_id':value['check_id'],'case_id':value['case_id'],'field':field,'original':old,'canonical':value[field]})
            for v in value.values():normalize_outcomes(v)
        elif isinstance(value,list):
            for v in value:normalize_outcomes(v)
    if task['scenario']=='code_review':normalize_outcomes(s)
    gold=load(ROOT/f"private/{task['id']}.json")
    abstentions={'missing input','missing_input','unsupported (traces unavailable)','unsupported: traces unavailable','unsupported (traces permanently unavailable; missing input)','unsupported (missing input)','unsupported (trace data unavailable)','unavailable','not available','unsupported'}
    if isinstance(s,dict) and isinstance(s.get('answer'),dict):
        for field in gold.get('unsupported_fields',[]):
            value=s['answer'].get(field)
            if isinstance(value,str) and value.strip().lower() in abstentions:
                s['answer'][field]='unsupported'
                if value!='unsupported':abstention_normalizations.append({'field':field,'original':value,'canonical':'unsupported','reason':'Unambiguous abstention in a contract-declared unavailable channel; not a numeric estimate.'})
        for c in s.get('claims',[]) if isinstance(s.get('claims',[]),list) else []:
            if isinstance(c,dict) and c.get('field') in gold.get('unsupported_fields',[]) and isinstance(c.get('value'),str) and c['value'].strip().lower() in abstentions:c['value']='unsupported'

    dp=ROOT/'qa/extra_claim_decisions.json';decisions=load(dp).get('decisions',{}) if dp.exists() else {}
    if isinstance(s,dict) and isinstance(s.get('claims'),list):
        kept=[]
        for c in s['claims']:
            decision=decisions.get(claim_review_key(task,c,artifacts)) if isinstance(c,dict) else None
            if decision:
                decided.append({'claim':c,'decision':decision});s.setdefault('evidence',[]).extend(c.get('evidence',[]))
            else:kept.append(c)
        s['claims']=kept
    ev=evaluate_repaired(task,s,artifacts,events,native)
    if decided:
        ev['explicit_claim_adjudications']=decided
        if any(not x['decision']['pass'] for x in decided):ev['success']=False;ev['task_contract_valid']=False;ev['evidence_valid']=False
    if task['scenario']=='code_review' and ev.get('unregistered_findings'):
        # This field explicitly requests registered case IDs. An unknown pair is
        # an invalid registered binding, not an unresolved novel-defect claim.
        gold=load(ROOT/f"private/{task['id']}.json");ev['registered_case_identity_valid']=False
        ev['success']=False;ev['task_contract_valid']=False
        if ev['status']=='ADJUDICATION_NEEDED' and not ev.get('extra_answer_fields') and not any(c.get('status')=='ADJUDICATION_NEEDED' for c in ev.get('claim_checks',[])) and not ev.get('repair_audit',{}).get('pending_symbol_relevance'):ev['status']='EVALUATED'
    ev['abstention_normalizations']=abstention_normalizations
    ev['outcome_normalizations']=outcome_normalizations
    ev['evaluation_policy']='R2_FINAL_OFFLINE_SCORER_1'
    return ev
