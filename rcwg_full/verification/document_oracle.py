"""Independent source-language oracle; no runtime, compiler, or replay imports."""
from collections import Counter
from copy import deepcopy
import re
from rcwg_full.evidence import canonical,digest
from .semantic import verify_semantics


def _span(doc,quote):
    at=doc['canonical_text'].index(quote)
    return {'document_id':doc['document_id'],'revision':doc['revision'],'start_cp':at,'end_cp':at+len(quote),'quote':quote}


def f5_expected(args):
    number=args['template'];stage=[];rate=[]
    for doc in args['documents']:
        text=doc['canonical_text'];sections={s['section_id']:s for s in doc['sections']};body=sections['result']['text']
        entity=re.search(r'The symbol A denotes ([^;]+);',text)[1]
        row={'query_id':'q-dose','paper_id':doc['document_id'],'entity_id':entity}
        if number==8:
            row.update(dose=None,status='refuted' if body.startswith('It is false') else 'unknown')
            quotes=[body] if row['status']=='refuted' else []
        elif number==10:
            versions=re.findall(r'Version (\d+): ([^ ]+) dose (\d+) mg, status (supported|refuted)\.',text)
            for version,ident,dose,status in versions:
                quote=f'Version {version}: {ident} dose {dose} mg, status {status}.'
                stage.append({**row,'version':int(version),'dose':int(dose),'status':status,'evidence':[_span(doc,quote)]})
            continue
        else:
            match=re.search(r'Entity ([^ ]+) has dose (\d+) (mg|g)\.',body)
            if match[1]!=entity:raise ValueError('FIXTURE_ENTITY_DEFINITION')
            row['dose']=int(match[2]);quotes=[match[0]]
            if number==2:
                row.update(unit=match[3],date=re.search(r'Date ([0-9-]+);',body)[1],confirmed='confirmed true.' in body);quotes=[body]
            if number==3:quotes=[sections['definition']['text'],match[0]]
            if number==6:quotes=[sections['result']['heading'],match[0]]
            if number==4:
                row['amount']=row.pop('dose');row['unit']=match[3]
                flag=re.search(r'Status for [^ ]+ is (supported|refuted)\.',body)
                row['status']=flag[1];quotes.append(flag[0])
        row['evidence']=[_span(doc,q) for q in quotes];stage.append(row)
        if number==7:stage.append({**deepcopy(row),'evidence':[_span(doc,sections['repeat']['text'])]})
        found=re.search(r'Entity ([^ ]+) has rate (\d+) per_day\.',text)
        rate.append({'query_id':'q-rate','paper_id':doc['document_id'],'entity_id':found[1],'rate':int(found[2]),'evidence':[_span(doc,found[0])]})
    result=deepcopy(stage)
    if number==4:
        result=[{**r,'normalized_mg':r['amount']*(1000 if r['unit']=='g' else 1)} for r in result if r['status']=='supported']
        result=[r for r in result if r['normalized_mg']>=1000]
    if number==7:
        result=[]
        for first,second in zip(stage[::2],stage[1::2]):result.append({**deepcopy(first),'evidence':deepcopy(first['evidence']+second['evidence'])})
    if number==9:
        first={}
        for row in stage:first.setdefault(row['entity_id'],row['dose'])
        result={'count_entities':len(first),'total_dose':sum(first.values())}
    if number==10:
        result=[]
        for paper in dict.fromkeys(r['paper_id'] for r in stage):
            rows=sorted((r for r in stage if r['paper_id']==paper),key=lambda r:r['version'],reverse=True)
            result.append({**deepcopy(rows[0]),'discarded_alternatives':deepcopy(rows[1:])})
    if number==11:result={'dose_branch':deepcopy(stage),'rate_branch':deepcopy(rate)}
    return {'result':result,'stages':{'extract_dose':stage,'extract_rate':rate} if number==11 else {'extract':stage}}


def _row_recipe(row):
    return {'fields':{k:{'acceptable_values':[v],'critical':True} for k,v in row.items() if k not in {'evidence','discarded_alternatives'}},
        'evidence_obligations':[{'id':str(i),'acceptable_witness_sets':[[c]]} for i,c in enumerate(row.get('evidence',[]))],
        'exact_fields':True}


def verify_rows(actual,expected,documents):
    if type(actual) is not list or len(actual)!=len(expected):return {'status':'FAIL','reason':'ROW_MULTIPLICITY'}
    originals={(d['document_id'],d['revision']):d['canonical_text'] for d in documents}
    for row in actual:
        if type(row) is not dict:return {'status':'FAIL','reason':'ROW_FORMAT'}
        for c in row.get('evidence',[]):
            try:
                text=originals[(c['document_id'],c['revision'])];a,b=c['start_cp'],c['end_cp']
                if type(a) is not int or type(b) is not int or not 0<=a<b<=len(text) or text[a:b]!=c['quote']:raise ValueError()
            except (KeyError,TypeError,ValueError):return {'status':'FAIL','reason':'SOURCE_CITATION'}
    def equal(row,gold):
        fields={k:v for k,v in row.items() if k not in {'evidence','public_span_check','discarded_alternatives'}}
        if verify_semantics({'fields':fields,'evidence':row.get('evidence',[])},_row_recipe(gold))['status']!='PASS':return False
        if not gold.get('evidence') and row.get('evidence'):return False
        if 'discarded_alternatives' in gold:
            return verify_rows(row.get('discarded_alternatives'),gold['discarded_alternatives'],documents)['status']=='PASS'
        return not row.get('discarded_alternatives')
    # Citation coordinates can differ while satisfying the same witness; do not
    # partition on coordinates or materialize the complete candidate graph.
    from .bag import capacity_equal
    passed=capacity_equal(actual,expected,equal,partition=lambda row:None)
    return {'status':'PASS' if passed else 'FAIL','rows_checked':len(actual),'source_quotes_checked':True}


def verify_document_result(actual,expected,documents,*,events=None,required_stages=None):
    result=expected['result']
    if type(result) is list:verification=verify_rows(actual,result,documents)
    elif result and all(type(v) is list for v in result.values()):
        checks={k:verify_rows(actual.get(k) if type(actual) is dict else None,rows,documents) for k,rows in result.items()}
        verification={'status':'PASS' if type(actual) is dict and set(actual)==set(result) and all(v['status']=='PASS' for v in checks.values()) else 'FAIL','branches':checks}
    else:verification={'status':'PASS' if canonical(actual)==canonical(result) else 'FAIL','comparison':'EXACT_DERIVED_AGGREGATE'}
    if events is not None:
        observed={};errors=[]
        for event in events:
            if event['event_kind']!='semantic_response':continue
            payload=event['payload'];name=payload['node_instance'].split('/')[-1].split('#')[0]
            if payload['response_sha256']!=digest(payload['rows']):errors.append('RESPONSE_HASH')
            observed.setdefault(name,[]).append(payload['rows'])
        checks={}
        for name,rows in expected['stages'].items():
            choices=[v for k,values in observed.items() if k==name or k.endswith(':'+name) for v in values]
            checks[name]=verify_rows(choices[0],rows,documents) if len(choices)==1 else {'status':'FAIL','reason':'STAGE_MULTIPLICITY','observed':list(observed)}
        if errors or len(observed)!=len(expected['stages']) or any(v['status']!='PASS' for v in checks.values()):verification['status']='FAIL'
        verification.update(stages=checks,errors=errors)
    verification['formal_gold_reviewed']=False
    return verification
