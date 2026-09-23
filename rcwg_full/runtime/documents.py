"""Frozen Unicode coordinates, public retrieval and evidence provenance adapters."""
from collections import Counter,defaultdict
from copy import deepcopy
import math
import re
from rcwg_full.evidence import canonical,digest,sha
from rcwg_full.runtime.scheduler import ExecutionFault

TOKENIZER={'id':'full001-unicode-word-punctuation-v1','pattern':r'\w+|[^\w\s]','flags':'UNICODE','normalization':'none','retrieval_term_transform':'casefold'}
BM25={'revision':'full001-bm25-1','k1':1.2,'b':0.75,'idf':'ln(1+(N-df+0.5)/(df+0.5))','tokenizer':TOKENIZER}


def tokens(text):
    text.encode('utf-8',errors='strict')
    return [{'token':m.group(),'start_cp':m.start(),'end_cp':m.end()} for m in re.finditer(TOKENIZER['pattern'],text)]


def canonical_document(document_id,revision,title,sections,*,source_record_id=None,metadata=None):
    pieces=[];out=[];offset=0
    for i,section in enumerate(sections):
        if i:pieces.append('\n\n');offset+=2
        heading=section.get('heading','');text=section['text'];start=offset
        if heading:pieces.append(heading+'\n');offset+=len(heading)+1
        body_start=offset;pieces.append(text);offset+=len(text)
        out.append({'section_id':section.get('section_id',str(i)),'heading':heading,'text':text,'start_cp':start,'body_start_cp':body_start,'end_cp':offset})
    text=''.join(pieces)
    return {'document_id':document_id,'source_record_id':document_id if source_record_id is None else source_record_id,
        'revision':revision,'title':title,'sections':out,'canonical_text':text,'canonical_text_sha256':sha(text.encode('utf-8')),'metadata':metadata or {}}


def validate_document(doc):
    text=doc['canonical_text'];text.encode('utf-8',errors='strict')
    if sha(text.encode())!=doc['canonical_text_sha256']:raise ValueError('DOCUMENT_TEXT_HASH')
    prior=-1;ids=set()
    for section in doc['sections']:
        a,b=section['start_cp'],section['end_cp'];body=section['body_start_cp']
        if not 0<=a<=body<=b<=len(text) or a<prior or section['section_id'] in ids:raise ValueError('SECTION_COORDINATES')
        if text[body:b]!=section['text']:raise ValueError('SECTION_TEXT_MISMATCH')
        if text[a:body]!=(section['heading']+'\n' if section['heading'] else ''):raise ValueError('HEADING_TEXT_MISMATCH')
        ids.add(section['section_id']);prior=b


def piece(doc,start,end):
    if not 0<=start<=end<=len(doc['canonical_text']):raise ValueError('SPAN_RANGE')
    return {'document_id':doc['document_id'],'revision':doc['revision'],'source_start_cp':start,'source_end_cp':end,'text':doc['canonical_text'][start:end]}


def compose(pieces):
    text='';segments=[]
    for item in pieces:
        if segments:text+='\n\n'
        start=len(text);text+=item['text']
        segments.append({k:v for k,v in item.items() if k!='text'}|{'presented_start_cp':start,'presented_end_cp':len(text)})
    return {'text':text,'segments':segments,'text_sha256':sha(text.encode('utf-8'))}


def map_presented_span(context,start,end):
    if type(start) is not int or type(end) is not int or not 0<=start<end<=len(context['text']):raise ValueError('SPAN_RANGE')
    # A citation crossing an inserted separator is not a single source span.
    matches=[s for s in context['segments'] if s['presented_start_cp']<=start and end<=s['presented_end_cp']]
    if len(matches)!=1:raise ValueError('NONCONTIGUOUS_CITATION')
    s=matches[0];offset=s['source_start_cp']-s['presented_start_cp']
    return {'document_id':s['document_id'],'revision':s['revision'],'start_cp':start+offset,'end_cp':end+offset,'quote':context['text'][start:end]}


class ReplaySemantic:
    """Explicit engineering replay, with exact request identity and no fallback."""
    def __init__(self,responses,*,mode,service_id='engineering-replay-e0'):
        if mode!='ENGINEERING_REPLAY':raise ValueError('REPLAY_MODE_FORBIDDEN')
        self.responses=deepcopy(responses);self.service_id=service_id;self.mode=mode;self.calls=[]
    async def extract(self,request):
        key=digest(request);self.calls.append({'request_hash':key,'service_id':self.service_id,'response_origin':'FIXED_ENGINEERING_REPLAY','paid_calls':0})
        if key not in self.responses:raise ExecutionFault('REPLAY_REQUEST_MISSING','facility')
        return deepcopy(self.responses[key])


class Documents:
    def __init__(self,documents,*,event=None,native=None,query_encoder=None):
        self.by_id={};self.event=event or (lambda *a:None);self.native=native;self.query_encoder=query_encoder
        self.read_count=Counter();self.logical_read_bytes=0
        for doc in documents:
            validate_document(doc);key=canonical(doc['document_id'])
            if key in self.by_id:raise ValueError('DUPLICATE_DOCUMENT_ID')
            self.by_id[key]=deepcopy(doc)
        self.native_bm25=None
        if self.native is not None:
            self.native_bm25=self.native.bm25_prepare([{'document_id':v['document_id'],'tokens':[t['token'].casefold() for t in tokens(v['canonical_text'])]} for v in self.by_id.values()])
            self.event('bm25_index_built',{'backend':'native_cpp20','counts':__import__('json').loads(self.native_bm25.construction())})
        self.tf={k:Counter(t['token'].casefold() for t in tokens(v['canonical_text'])) for k,v in self.by_id.items()} if self.native is None else {}
        self.length={k:sum(v.values()) for k,v in self.tf.items()}
        self.df=Counter(term for tf in self.tf.values() for term in tf)
        self.index_hash=digest({'documents':[(k.decode(),d['canonical_text_sha256']) for k,d in self.by_id.items()],'profile':BM25})

    def document(self,ident):
        key=canonical(ident)
        if key not in self.by_id:raise ExecutionFault('DOCUMENT_ID_UNAVAILABLE')
        return self.by_id[key]

    def record_read(self,doc,start,end,operation,kind):
        size=len(doc['canonical_text'][start:end].encode('utf-8'));self.logical_read_bytes+=size;self.read_count[(canonical(doc['document_id']),doc['revision'])]+=1
        self.event('document_read',{'document_id':doc['document_id'],'revision':doc['revision'],'start_cp':start,'end_cp':end,'logical_read_bytes':size,'operation_id':operation,'kind':kind})

    def retrieve(self,query,limit,offset=0):
        if self.native_bm25 is not None:
            result,counts=self.native.bm25_query(self.native_bm25,[t['token'].casefold() for t in tokens(query)],limit,offset)
            self.event('bm25_query',{'backend':'native_cpp20','counts':counts,'index_hash':self.index_hash});return result
        terms=Counter(t['token'].casefold() for t in tokens(query));N=len(self.by_id);avg=sum(self.length.values())/N if N else 0;ranked=[]
        for key,tf in self.tf.items():
            score=0.0
            for term,qf in terms.items():
                freq=tf[term]
                if freq:
                    idf=math.log(1+(N-self.df[term]+.5)/(self.df[term]+.5));denom=freq+1.2*(1-.75+.75*self.length[key]/avg)
                    score+=qf*idf*freq*2.2/denom
            ranked.append((score,self.by_id[key]['document_id']))
        ranked.sort(key=lambda x:(-x[0],x[1]))
        return [{'document_id':ident,'score':score} for score,ident in ranked[offset:offset+limit]]

    def read_documents(self,ids,fields,batch_size,impl,operation,id_field='document_id'):
        rows=[];group=[]
        for item in ids:
            ident=item[id_field] if isinstance(item,dict) else item;doc=self.document(ident)
            self.record_read(doc,0,len(doc['canonical_text']),operation,impl)
            selected={k:deepcopy(doc[k]) for k in fields}
            # Provenance travels beside selected public fields, never as hidden labels.
            selected['_source']={'document_id':doc['document_id'],'revision':doc['revision'],'content_sha256':doc['canonical_text_sha256']}
            group.append(selected)
            if len(group)>=(batch_size if impl=='batched' else 1):rows.extend(group);self.event('document_batch',{'count':len(group),'implementation':impl,'operation_id':operation});group=[]
        if group:rows.extend(group);self.event('document_batch',{'count':len(group),'implementation':impl,'operation_id':operation})
        return rows

    def selected_context(self,source):
        meta=source.get('_source',source);doc=self.document(meta['document_id'])
        if meta['revision']!=doc['revision']:raise ExecutionFault('DOCUMENT_REVISION_MISMATCH')
        if 'canonical_text' in source:
            if source['canonical_text']!=doc['canonical_text']:raise ExecutionFault('DOCUMENT_SELECTED_TEXT_MISMATCH')
            return compose([piece(doc,0,len(doc['canonical_text']))])
        if 'sections' in source:
            if source['sections']!=doc['sections']:raise ExecutionFault('DOCUMENT_SELECTED_SECTIONS_MISMATCH')
            return compose([piece(doc,s['start_cp'],s['end_cp']) for s in source['sections']])
        raise ExecutionFault('DOCUMENT_TEXT_NOT_SELECTED')

    def validate_context(self,context):
        if sha(context['text'].encode('utf8'))!=context['text_sha256']:raise ExecutionFault('CONTEXT_TEXT_HASH')
        prior=0
        for segment in context['segments']:
            doc=self.document(segment['document_id']);a,b=segment['source_start_cp'],segment['source_end_cp'];x,y=segment['presented_start_cp'],segment['presented_end_cp']
            if any(type(v) is not int for v in [a,b,x,y]) or not 0<=a<=b<=len(doc['canonical_text']) or not prior<=x<=y<=len(context['text']):raise ExecutionFault('CONTEXT_SEGMENT_RANGE')
            if segment['revision']!=doc['revision'] or context['text'][x:y]!=doc['canonical_text'][a:b]:raise ExecutionFault('CONTEXT_SEGMENT_MISMATCH')
            if context['text'][prior:x] not in {'','\n\n'}:raise ExecutionFault('CONTEXT_INSERTED_TEXT')
            prior=y
        if prior!=len(context['text']):raise ExecutionFault('CONTEXT_UNMAPPED_SUFFIX')

    def split(self,documents,size,overlap,impl):
        result=[]
        for source in documents:
            meta=source.get('_source',source);doc=self.document(meta['document_id'])
            self.selected_context(source)
            if meta['revision']!=doc['revision']:raise ExecutionFault('DOCUMENT_REVISION_MISMATCH')
            ranges=[(s['start_cp'],s['end_cp'],s['section_id']) for s in doc['sections']] if impl=='section' else [(0,len(doc['canonical_text']),None)]
            for a,b,section in ranges:
                ts=tokens(doc['canonical_text'][a:b])
                for pos in range(0,len(ts),size-overlap):
                    selected=ts[pos:pos+size];start=a+selected[0]['start_cp'];end=a+selected[-1]['end_cp']
                    result.append({'document_id':doc['document_id'],'revision':doc['revision'],'section_id':section,'chunk_ordinal':len(result),**compose([piece(doc,start,end)])})
                    if pos+size>=len(ts):break
        return result

    def gather(self,chunks,window,impl,operation):
        result=[]
        for chunk in chunks:
            self.validate_context(chunk)
            segments=[]
            for segment in chunk['segments']:
                doc=self.document(segment['document_id'])
                if segment['revision']!=doc['revision']:raise ExecutionFault('DOCUMENT_REVISION_MISMATCH')
                selected=[i for i,s in enumerate(doc['sections']) if s['start_cp']<segment['source_end_cp'] and segment['source_start_cp']<s['end_cp']]
                if impl=='neighbors':
                    indices=sorted({j for i in selected for j in range(max(0,i-window),min(len(doc['sections']),i+window+1))})
                    for j in indices:
                        s=doc['sections'][j];segments.append(piece(doc,s['start_cp'],s['end_cp']));self.record_read(doc,s['start_cp'],s['end_cp'],operation,impl)
                else:
                    for i in selected:
                        s=doc['sections'][i]
                        if s['heading']:segments.append(piece(doc,s['start_cp'],s['body_start_cp']));self.record_read(doc,s['start_cp'],s['body_start_cp'],operation,impl)
                    segments.append(piece(doc,segment['source_start_cp'],segment['source_end_cp']))
            seen=set();unique=[]
            for s in segments:
                identity=(canonical(s['document_id']),s['revision'],s['source_start_cp'],s['source_end_cp'])
                if identity not in seen:seen.add(identity);unique.append(s)
            result.append({k:v for k,v in chunk.items() if k not in {'text','segments','text_sha256'}}|compose(unique))
        return result

    def span_check(self,evidence,strict):
        out=[]
        for item in evidence:
            valid=True;causes=[]
            for citation in item.get('evidence',[]):
                try:
                    doc=self.document(citation['document_id']);a=citation['start_cp'];b=citation['end_cp']
                    if citation['revision']!=doc['revision'] or type(a) is not int or type(b) is not int or not 0<=a<b<=len(doc['canonical_text']) or doc['canonical_text'][a:b]!=citation['quote']:raise ValueError('SPAN_OR_REVISION')
                except (KeyError,ValueError,ExecutionFault) as exc:valid=False;causes.append(str(exc))
            if strict and not valid:raise ExecutionFault('PUBLIC_SPAN_INVALID')
            out.append(deepcopy(item)|{'public_span_check':{'status':'PASS' if valid else 'FAIL','causes':causes,'semantic_support':'NOT_ASSESSED'}})
        return out

    def merge(self,evidence,keys,policy,priority=None):
        groups=defaultdict(list)
        for item in evidence:groups[digest([item[k] for k in keys])].append(item)
        output=[]
        for items in groups.values():
            claims={digest({k:v for k,v in item.items() if k not in {'evidence','provenance','public_span_check'}}) for item in items}
            if len(claims)>1 and policy=='reject':raise ExecutionFault('EVIDENCE_CONFLICT')
            if policy=='declared_priority':
                items=list(items)
                for rule in reversed(priority):items.sort(key=lambda x:(x[rule['field']] is None,x[rule['field']]),reverse=rule['direction']=='desc')
                selected=deepcopy(items[0]);selected['discarded_alternatives']=deepcopy(items[1:]);output.append(selected)
            else:
                claims={}
                for item in items:
                    key=digest({k:v for k,v in item.items() if k not in {'evidence','provenance','public_span_check'}})
                    if key not in claims:claims[key]=deepcopy(item)
                    else:
                        evidence=claims[key].setdefault('evidence',[]);seen={digest(c) for c in evidence}
                        for citation in item.get('evidence',[]):
                            if digest(citation) not in seen:evidence.append(deepcopy(citation));seen.add(digest(citation))
                output.extend(claims.values())
        return output

    async def dispatch(self,op,impl,inputs,p,*,semantic,instance,scheduler,node):
        if op=='text_retrieve':
            if impl=='bm25':return await scheduler.compute(instance,node,self.retrieve,p['query'],p['limit'],p.get('offset',0))
            if self.query_encoder is None:raise ExecutionFault('DENSE_ENCODER_UNAVAILABLE','facility')
            import time
            started=time.monotonic_ns()
            vector=await scheduler.compute(instance,node,self.query_encoder.encode,p['query'])
            encoding_ns=time.monotonic_ns()-started
            docs=[{'document_id':d['document_id'],'vector':d['vector']} for d in self.by_id.values()]
            result,c=await scheduler.compute(instance,node,self.native.dense,docs,vector,p)
            self.event('dense_query',{'encoder_hash':self.query_encoder.identity,'counts':c,'origin':self.query_encoder.origin,
                'query_sha256':sha(p['query'].encode('utf8')),'query_encoding_elapsed_ns':encoding_ns,
                'query_utf8_bytes':len(p['query'].encode('utf8')),'query_tokens':len(tokens(p['query'])),
                'encoded_vector_sha256':digest(vector),'paid_calls':0,'encoding_in_execution_clock':True})
            return result
        if op=='read_documents':return self.read_documents(inputs['ids'].to_pylist() if hasattr(inputs['ids'],'to_pylist') else inputs['ids'],p['fields'],p['batch_size'],impl,instance,p.get('id_field','document_id'))
        if op=='split_documents':return self.split(inputs['documents'],p['size'],p['overlap'],impl)
        if op=='gather_context':return self.gather(inputs['chunks'],p['window'],impl,instance)
        if op=='evidence_validate':return self.span_check(inputs['evidence'],p['strict'])
        if op=='evidence_merge':return self.merge(inputs['evidence'],p['keys'],p['conflict_policy'],p.get('priority_rule'))
        if semantic is None:raise ExecutionFault('SEMANTIC_SERVICE_NOT_READY','facility')
        documents=inputs['documents'];contexts=[]
        for item in documents:
            if 'segments' in item:self.validate_context(item);contexts.append(item)
            else:contexts.append(self.selected_context(item))
        if sum(len(tokens(c['text'])) for c in contexts)>p['context_budget']:raise ExecutionFault('CONTEXT_LIMIT_EXCEEDED')
        request={'service_id':semantic.service_id,'question':p.get('question',self.task_question()),'field_schema':p['field_schema'],'contexts':contexts}
        self.event('semantic_request',{'request_hash':digest(request),'origin':semantic.mode,'context_tokens':sum(len(tokens(c['text'])) for c in contexts)})
        result=await semantic.extract(request)
        if not isinstance(result,list):raise ExecutionFault('SEMANTIC_RESPONSE_SCHEMA','service')
        from rcwg_full.runtime.values import validate
        for row in result:
            if type(row) is not dict or set(row)-set(p['field_schema'])-{'evidence'} or set(p['field_schema'])-set(row):raise ExecutionFault('SEMANTIC_RESPONSE_SCHEMA','service')
            try:
                from rcwg_full.compiler.typesystem import parse_schema,type_json
                schema={k:type_json(t) for k,t in parse_schema(p['field_schema'],'/semantic/field_schema').items()}
                validate({k:row[k] for k in schema},{'kind':'Record','schema':schema},None)
            except (ValueError,TypeError,KeyError) as exc:raise ExecutionFault('SEMANTIC_RESPONSE_SCHEMA','service') from exc
            citations=row.get('evidence',[])
            if type(citations) is not list:raise ExecutionFault('SEMANTIC_RESPONSE_SCHEMA','service')
            for citation in citations:
                try:
                    if set(citation)!={'document_id','revision','start_cp','end_cp','quote'}:raise ValueError('CITATION_FIELDS')
                    a,b=citation['start_cp'],citation['end_cp']
                    if type(a) is not int or type(b) is not int or a>=b:raise ValueError('CITATION_RANGE')
                    doc=self.document(citation['document_id'])
                    if citation['revision']!=doc['revision'] or doc['canonical_text'][a:b]!=citation['quote']:raise ValueError('CITATION_CONTENT')
                    ranges=sorted((s['source_start_cp'],s['source_end_cp']) for c in contexts for s in c['segments'] if s['document_id']==citation['document_id'] and s['revision']==citation['revision'])
                    covered=a
                    for x,y in ranges:
                        if x<=covered:covered=max(covered,y)
                    if covered<b:raise ValueError('CITATION_NOT_PRESENTED')
                except (ValueError,KeyError,TypeError,ExecutionFault) as exc:raise ExecutionFault('SEMANTIC_CITATION_NOT_IN_CONTEXT','service') from exc
        self.event('semantic_response',{'request_hash':digest(request),'question':request['question'],
            'node_instance':instance,'origin':semantic.mode,'rows':result,'response_sha256':digest(result),
            'visibility':'PRIVATE_EXECUTION_EVIDENCE'})
        return result

    def task_question(self):return 'explicit engineering extraction'
