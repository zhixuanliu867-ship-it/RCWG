import asyncio
from copy import deepcopy
import os
import unittest
from rcwg_full.evidence import digest
from rcwg_full.runtime.documents import Documents,ReplaySemantic,canonical_document,piece,compose,tokens
from rcwg_full.runtime.native import Native
from rcwg_full.runtime.scheduler import ExecutionFault


class InlineScheduler:
    async def compute(self,instance,node,fn,*args):return fn(*args)


class DocumentClosure(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.doc=canonical_document('paper1','v1','Title',[{'heading':'定义','text':'实体甲 dose = 5 mg.'},{'heading':'追加','text':'对象乙 dose = 7 mg.'}])
        self.docs=Documents([self.doc]);self.params={'field_schema':{'query_id':'Utf8','dose':'Int64'},'question':'甲的剂量，query_id=q1','context_budget':1000}
        self.context=compose([piece(self.doc,0,self.doc['sections'][0]['end_cp'])])
        self.reply={'query_id':'q1','dose':5,'evidence':[{'document_id':'paper1','revision':'v1','start_cp':self.doc['canonical_text'].index('5 mg'), 'end_cp':self.doc['canonical_text'].index('5 mg')+4,'quote':'5 mg'}]}
    async def run_reply(self,reply,context=None):
        contexts=[self.context if context is None else context]
        request={'service_id':'engineering-replay-e0','question':self.params['question'],'field_schema':self.params['field_schema'],'contexts':contexts}
        replay=ReplaySemantic({digest(request):reply},mode='ENGINEERING_REPLAY')
        return await self.docs.dispatch('semantic_extract','structured',{'documents':contexts},self.params,semantic=replay,instance='extract',scheduler=InlineScheduler(),node={})
    async def test_exact_request_schema_and_presented_citation(self):self.assertEqual(await self.run_reply([self.reply]),[self.reply])
    async def test_missing_extra_bool_and_nonfinite_fields_fail(self):
        for mutate in ['missing','extra','bool','float']:
            row=deepcopy(self.reply)
            if mutate=='missing':row.pop('query_id')
            elif mutate=='extra':row['gold']='forbidden'
            elif mutate=='bool':row['dose']=True
            else:row['dose']=5.0
            with self.assertRaisesRegex(ExecutionFault,'SEMANTIC_RESPONSE_SCHEMA'):await self.run_reply([row])
    async def test_citation_elsewhere_in_document_is_not_presented_evidence(self):
        row=deepcopy(self.reply);at=self.doc['canonical_text'].index('7 mg');row['evidence'][0].update(start_cp=at,end_cp=at+4,quote='7 mg')
        with self.assertRaisesRegex(ExecutionFault,'SEMANTIC_CITATION_NOT_IN_CONTEXT'):await self.run_reply([row])
    async def test_fabricated_context_and_revision_fail_before_service(self):
        context=deepcopy(self.context);context['text']+='hidden'
        with self.assertRaisesRegex(ExecutionFault,'CONTEXT_TEXT_HASH'):await self.run_reply([self.reply],context)
        context=deepcopy(self.context);context['segments'][0]['revision']='wrong'
        with self.assertRaisesRegex(ExecutionFault,'CONTEXT_SEGMENT_MISMATCH'):await self.run_reply([self.reply],context)
    async def test_title_only_read_cannot_restore_hidden_body(self):
        docs=self.docs.read_documents(['paper1'],['title'],1,'batched','read')
        with self.assertRaisesRegex(ExecutionFault,'DOCUMENT_TEXT_NOT_SELECTED'):self.docs.split(docs,16,0,'section')
        with self.assertRaisesRegex(ExecutionFault,'DOCUMENT_TEXT_NOT_SELECTED'):
            await self.docs.dispatch('semantic_extract','structured',{'documents':docs},self.params,semantic=ReplaySemantic({},mode='ENGINEERING_REPLAY'),instance='x',scheduler=InlineScheduler(),node={})
    async def test_explicit_table_id_field_is_resolved(self):
        result=self.docs.read_documents([{'paper_id':'paper1'}],['canonical_text'],1,'batched','read','paper_id')
        self.assertEqual(result[0]['_source']['document_id'],'paper1')

    async def test_duplicate_support_merges_all_source_citations(self):
        first=deepcopy(self.reply);second=deepcopy(first)
        second['evidence'][0].update(document_id='paper2',revision='v2')
        merged=self.docs.merge([first,second,first],['query_id'],'keep_all')
        self.assertEqual(len(merged),1);self.assertEqual(merged[0]['evidence'],first['evidence']+second['evidence'])


class NativeBm25(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.native=Native(os.environ['RCWG_FULL_BUILD'],'diagnostic')
    def test_native_index_and_scoring_agree_with_independent_formula(self):
        import math
        docs=[canonical_document(i,'v1','',[{'text':text}]) for i,text in enumerate(['cat cat dog','cat dog dog','bird bird','', '🙂 cat'])]
        observed=[];store=Documents(docs,native=self.native,event=lambda k,v:observed.append((k,v)))
        for query in ['cat','cat cat dog','absent','🙂','']:
            words=[t['token'].casefold() for t in tokens(query)];texts=[[t['token'].casefold() for t in tokens(d['canonical_text'])] for d in docs]
            average=sum(map(len,texts))/len(texts);expected=[]
            for ident,words_in_doc in enumerate(texts):
                score=0.
                for term in sorted(set(words)):
                    freq=words_in_doc.count(term);df=sum(term in text for text in texts)
                    if freq:score+=words.count(term)*math.log(1+(len(texts)-df+.5)/(df+.5))*freq*2.2/(freq+1.2*(.25+.75*len(words_in_doc)/average))
                expected.append({'document_id':ident,'score':score})
            expected.sort(key=lambda r:(-r['score'],r['document_id']))
            actual=store.retrieve(query,3,1)
            self.assertEqual([r['document_id'] for r in actual],[r['document_id'] for r in expected[1:4]])
            for a,b in zip(actual,expected[1:4]):self.assertAlmostEqual(a['score'],b['score'],places=12)
        self.assertTrue(any(k=='bm25_index_built' and v['counts']['index_documents']==5 for k,v in observed))
        self.assertTrue(any(k=='bm25_query' and v['counts'].get('postings_scored',0)>0 for k,v in observed))
    def test_empty_and_zero_length_documents_have_finite_tied_scores(self):
        self.assertEqual(Documents([],native=self.native).retrieve('word',2),[])
        store=Documents([canonical_document(str(i),'v1','',[{'text':''}]) for i in [2,1]],native=self.native)
        self.assertEqual(store.retrieve('word',5),[{'document_id':'1','score':0.},{'document_id':'2','score':0.}])

    def test_nested_citation_payload_survives_all_join_kernels(self):
        import pyarrow as pa
        citation=pa.struct([pa.field('document_id',pa.string()),pa.field('start_cp',pa.int64()),pa.field('quote',pa.string())])
        schema=pa.schema([('id',pa.int64()),('evidence',pa.list_(citation))])
        rows=[{'id':1,'evidence':[{'document_id':'甲','start_cp':3,'quote':'中🙂'}]},{'id':2,'evidence':[]},{'id':3,'evidence':None}]
        left=pa.Table.from_pylist(rows,schema=schema);right=pa.table({'key':[1,2,3],'flag':[True,False,True]})
        expected=[{**row,'key':i+1,'flag':i!=1} for i,row in enumerate(rows)]
        for implementation in ['hash','sort_merge','block_nested']:
            actual,_=self.native.relational('join',implementation,left,{'keys':[{'left':'id','right':'key'}],'join_type':'inner','build_side':'right'},right)
            self.assertEqual(actual.to_pylist(),expected)
        projected,_=self.native.relational('project','copy',left,{'columns':['id'],'expressions':{'copied':{'field':'evidence'}},'_field_types':{'copied':{'kind':'Nullable','item':{'kind':'List','max_length':16,'item':{'kind':'Record','schema':{'document_id':'Utf8','quote':'Utf8','start_cp':'Int64'}}}}}})
        self.assertEqual(projected.to_pylist(),[{'id':r['id'],'copied':r['evidence']} for r in rows])
