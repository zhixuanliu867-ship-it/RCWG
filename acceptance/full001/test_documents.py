import copy
import math
import unittest
from rcwg_full.runtime.documents import canonical_document,validate_document,tokens,Documents,ReplaySemantic,piece,compose,map_presented_span
from rcwg_full.runtime.scheduler import ExecutionFault
from rcwg_full.evidence import digest


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc=canonical_document('d1','r1','Title',[{'heading':'一🙂','text':'Alpha beta. 不支持剂量 5 mg。'},{'heading':'Second','text':'Alpha gamma delta. 日期 2026-01-02。'}])
        self.events=[];self.store=Documents([self.doc],event=lambda k,v:self.events.append((k,v)))
    def test_canonical_codepoints_and_tamper(self):
        validate_document(self.doc)
        second=self.doc['sections'][1];self.assertEqual(self.doc['canonical_text'][second['body_start_cp']:second['end_cp']],second['text'])
        text=self.doc['canonical_text'];pos=text.index('🙂');self.assertNotEqual(len(text[:pos+1]),len(text[:pos+1].encode()))
        bad=copy.deepcopy(self.doc);bad['canonical_text']=bad['canonical_text'].replace('mg','g')
        with self.assertRaisesRegex(ValueError,'HASH'):validate_document(bad)
    def test_frozen_token_boundaries_and_overlapping_chunks(self):
        docs=self.store.read_documents(['d1'],['canonical_text'],1,'per_document','read1')
        chunks=self.store.split(docs,5,2,'token_window');self.assertGreater(len(chunks),2)
        original=tokens(self.doc['canonical_text'])
        for i,chunk in enumerate(chunks):
            span=chunk['segments'][0];self.assertEqual(span['source_start_cp'],original[i*3]['start_cp'])
            self.assertEqual(chunk['text'],self.doc['canonical_text'][span['source_start_cp']:span['source_end_cp']])
        self.assertEqual(chunks[-1]['segments'][0]['source_end_cp'],original[-1]['end_cp'])
    def test_piecewise_gather_cannot_cite_inserted_separator(self):
        context=compose([piece(self.doc,0,2),piece(self.doc,10,15)])
        self.assertEqual(map_presented_span(context,4,6)['start_cp'],10)
        with self.assertRaisesRegex(ValueError,'NONCONTIGUOUS'):map_presented_span(context,1,5)
        citation=map_presented_span(context,4,6)
        self.assertEqual(self.store.span_check([{'evidence':[citation]}],True)[0]['public_span_check']['semantic_support'],'NOT_ASSESSED')
    def test_public_span_does_not_assert_semantics_and_rejects_revision(self):
        a=self.doc['canonical_text'].index('不支持');quote=self.doc['canonical_text'][a:a+3]
        evidence={'value':True,'evidence':[{'document_id':'d1','revision':'r1','start_cp':a,'end_cp':a+3,'quote':quote}]}
        result=self.store.span_check([evidence],True)[0]
        self.assertEqual(result['public_span_check']['status'],'PASS');self.assertEqual(result['public_span_check']['semantic_support'],'NOT_ASSESSED')
        evidence['evidence'][0]['revision']='r2'
        with self.assertRaisesRegex(ExecutionFault,'SPAN_INVALID'):self.store.span_check([evidence],True)
        self.assertEqual(self.store.span_check([evidence],False)[0]['public_span_check']['status'],'FAIL')
    def test_conflict_policy_retains_evidence_and_alternatives(self):
        rows=[{'entity':'x','value':True,'priority':1,'evidence':[{'quote':'supports'}]},{'entity':'x','value':False,'priority':2,'evidence':[{'quote':'denies'}]}]
        self.assertEqual(self.store.merge(rows,['entity'],'keep_all'),rows)
        with self.assertRaisesRegex(ExecutionFault,'CONFLICT'):self.store.merge(rows,['entity'],'reject')
        selected=self.store.merge(rows,['entity'],'declared_priority',[{'field':'priority','direction':'desc'}])[0]
        self.assertFalse(selected['value']);self.assertEqual(selected['discarded_alternatives'],[rows[0]])
    def test_bm25_independent_formula_and_id_tie(self):
        docs=[canonical_document(str(i),'r','', [{'text':text}]) for i,text in enumerate(['cat cat dog','cat dog dog','bird bird'])]
        store=Documents(docs);ranked=store.retrieve('cat',3);N=3;df=2;avg=8/3
        expected=math.log(1+(N-df+.5)/(df+.5))*2*2.2/(2+1.2*(.25+.75*3/avg))
        self.assertEqual(ranked[0]['document_id'],'0');self.assertAlmostEqual(ranked[0]['score'],expected)
        self.assertEqual(store.retrieve('absent',3),[{'document_id':str(i),'score':0.0} for i in range(3)])
    def test_actual_read_batching_and_gather_reads(self):
        self.store.read_documents(['d1','d1'],['canonical_text'],2,'batched','one')
        self.assertEqual([e[1]['count'] for e in self.events if e[0]=='document_batch'],[2])
        self.assertEqual(self.store.logical_read_bytes,2*len(self.doc['canonical_text'].encode()))
        chunks=self.store.split([self.doc],5,0,'section');before=self.store.logical_read_bytes
        gathered=self.store.gather(chunks[:1],1,'neighbors','gather')
        self.assertGreater(self.store.logical_read_bytes,before);self.assertEqual(len(gathered[0]['segments']),2)


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_replay_exact_identity_and_no_formal_fallback(self):
        request={'question':'engineering','contexts':[]};reply=[{'value':False}]
        service=ReplaySemantic({digest(request):reply},mode='ENGINEERING_REPLAY')
        self.assertEqual(await service.extract(request),reply);self.assertEqual(service.calls[0]['paid_calls'],0)
        with self.assertRaisesRegex(ExecutionFault,'REPLAY_REQUEST_MISSING'):await service.extract({'question':'changed','contexts':[]})
        with self.assertRaisesRegex(ValueError,'REPLAY_MODE_FORBIDDEN'):ReplaySemantic({},mode='FORMAL')
