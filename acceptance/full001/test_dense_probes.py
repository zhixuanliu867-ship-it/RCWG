import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from rcwg_full.runtime.dense_encoder import FrozenTokenEncoder,PROFILE,bind_encoder
from rcwg_full.runtime.probes import probe
from rcwg_full.runtime.catalog import DataCatalog,DataSource
from rcwg_full.data.prepare import prepare
from rcwg_full.data.templates import task_shell,descriptor
from support import EvidenceDirectory


class DenseProbeSoftware(unittest.TestCase):
    def test_numeric_model_unicode_oov_empty_and_no_hidden_mutation(self):
        model={'profile':PROFILE,'model_id':'toy','dimension':2,'normalize':False,'weights':{'red':[2.,0.],'🙂':[0.,2.]},
            'oov':[0.,0.],'provenance':{'origin':'HAND_AUTHORED_ENGINEERING_WEIGHTS','license':'test fixture','source_revision':'v1'}}
        encoder=FrozenTokenEncoder(model);model['weights']['red'][0]=999
        self.assertEqual(encoder.encode('RED 🙂 unknown'),[2/3,2/3]);self.assertEqual(encoder.encode(''),[0.,0.])
        self.assertNotEqual(encoder.encode('RED'),[999.,0.])
        for change in [{'weights':{'two tokens':[1.,0.]}},{'oov':[float('nan'),0.]},{'dimension':True}]:
            with self.subTest(change=list(change)),self.assertRaises(ValueError):FrozenTokenEncoder({**model,**change})

    def test_public_metadata_and_bounded_sample_never_collect_source(self):
        import pyarrow as pa
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        rows=[{'id':i,'score':float(i)} for i in range(37)]
        task=task_shell('F1-01',0,'C0','Probe',{'id':'result','type':'records','mode':'exact','fields':['id'],'schema':{'id':'Int64'}})
        task['datasets']=[descriptor('records',{'id':'Int64','score':'Float64'},rows)]
        task,_,path=prepare(task,{'dataset:records':pa.Table.from_pylist(rows)},root/'data');source=DataCatalog(path).bind(task).resolve('dataset:records')
        events=[]
        with patch.object(DataSource,'table',side_effect=AssertionError('WHOLE_TABLE_FORBIDDEN')):
            with patch.object(DataSource,'batches',side_effect=AssertionError('METADATA_READ_FORBIDDEN')):
                result=probe(source,'metadata',{'fields':['id']},lambda k,v:events.append((k,v)))
            self.assertEqual(result['public_stats'],task['datasets'][0]['stats']);self.assertEqual(events[-1][1]['source_rows_read'],0)
            result=probe(source,'sample',{'fields':['id'],'sample_size':5},lambda k,v:events.append((k,v)))
        self.assertEqual(result['sample'],[{'id':i} for i in [1,3,5,8,18]])
        ledger=events[-1][1];self.assertEqual(ledger['logical_read_bytes'],37*8)
        self.assertEqual(ledger['source_rows_read'],37);self.assertGreater(ledger['physical_integrity_read_bytes'],0)
        self.assertTrue(all(v['columns']==['id'] for k,v in events if k=='source_batch'))

    def test_dense_model_file_vector_and_public_model_binding_fail_closed(self):
        from rcwg_full.data.dense import prepare_dense
        from rcwg_full.data.document_templates import document_descriptor,DOMAIN,REVISION
        from rcwg_full.runtime.documents import canonical_document
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        docs=[canonical_document('a',REVISION,'',[{'text':'red'}])]
        task=task_shell('F5-01',0,'C0','Retrieve',{'id':'result','type':'id_set','mode':'exact','item_type':'Utf8','domain':DOMAIN,'revision':REVISION})
        task['datasets']=[document_descriptor('documents',docs)]
        model={'profile':PROFILE,'model_id':'toy','dimension':2,'normalize':False,'weights':{'red':[1.,0.]},'oov':[0.,0.],
            'provenance':{'origin':'HAND_AUTHORED_ENGINEERING_WEIGHTS','license':'fixture','source_revision':'v1'}}
        task,_,path=prepare_dense(task,{'dataset:documents':docs},{'dataset:documents':model},root/'data')
        source=DataCatalog(path).bind(task).resolve('dataset:documents');documents=source.value()
        self.assertEqual(bind_encoder(source,documents).encode('red'),[1.,0.])
        changed=copy.deepcopy(documents);changed[0]['vector']=[0.,1.]
        with self.assertRaisesRegex(ValueError,'DENSE_INDEX_ENCODING_MISMATCH'):bind_encoder(source,changed)
        source.public['dense_model_id']='changed'
        with self.assertRaisesRegex(ValueError,'DENSE_MODEL_BINDING'):bind_encoder(source,documents)
        source.public['dense_model_id']='toy';asset=source.path(source.entry['dense_encoder']['model_file'])
        with asset.open('ab') as f:f.write(b' ')
        with self.assertRaisesRegex(ValueError,'DATA_FILE_HASH'):bind_encoder(source,documents)
