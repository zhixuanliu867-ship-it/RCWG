import copy
import json
import unittest
from pathlib import Path
from rcwg_full.evidence import canonical,digest,sha
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.data.prepare import prepare
from rcwg_full.data.graph_templates import f3
from rcwg_full.data.templates import build
from rcwg_full.data.conditions import check_group
from support import EvidenceDirectory


class ActualSources(unittest.TestCase):
    def setUp(self):self.tmp=EvidenceDirectory(self.id());self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def graph(self,mutation=None):
        case=f3('F3-01',0,'C0')
        if mutation:mutation(case)
        task,manifest,path=prepare(case['task'],{'dataset:'+k:v for k,v in case['rows'].items()},self.root/'data')
        return DataCatalog(path).bind(task)

    def test_actual_graph_and_seed_sources_pass(self):
        catalog=self.graph();observed=catalog.audit()
        self.assertEqual(observed,{s.entry['source_id']:s.entry['logical_content_sha256'] for s in catalog.sources.values()})

    def test_rehashed_unknown_endpoint_fails(self):
        catalog=self.graph(lambda c:c['rows']['graph']['edges'][0].update(dst=999))
        with self.assertRaisesRegex(ValueError,'GRAPH_UNKNOWN_ENDPOINT'):catalog.audit()

    def test_rehashed_duplicate_node_fails(self):
        catalog=self.graph(lambda c:c['rows']['graph']['nodes'][1].update(node_id=0))
        with self.assertRaisesRegex(ValueError,'GRAPH_DUPLICATE_NODE'):catalog.audit()

    def test_rehashed_weight_claim_fails(self):
        catalog=self.graph(lambda c:c['rows']['graph']['edges'][0].update(weight=-1.))
        with self.assertRaisesRegex(ValueError,'GRAPH_WEIGHT_NONNEGATIVE'):catalog.audit()

    def test_rehashed_equal_weight_claim_fails(self):
        catalog=self.graph(lambda c:c['rows']['graph']['edges'][0].update(weight=2.))
        with self.assertRaisesRegex(ValueError,'GRAPH_WEIGHT_EQUAL'):catalog.audit()

    def test_rehashed_wrong_actual_scalar_type_fails(self):
        catalog=self.graph(lambda c:c['rows']['graph']['nodes'][0].update(node_id=False))
        with self.assertRaisesRegex(ValueError,'RUNTIME_TYPE'):catalog.audit()

    def test_rehashed_duplicate_edge_id_fails(self):
        catalog=self.graph(lambda c:c['rows']['graph']['edges'][1].update(edge_id=0))
        with self.assertRaisesRegex(ValueError,'GRAPH_DUPLICATE_EDGE'):catalog.audit()

    def test_rehashed_index_incomplete_fails(self):
        catalog=self.graph(lambda c:c['rows']['graph']['edge_index'].pop())
        with self.assertRaisesRegex(ValueError,'GRAPH_INDEX_PERMUTATION'):catalog.audit()

    def test_rehashed_index_wrong_order_fails(self):
        catalog=self.graph(lambda c:c['rows']['graph']['edge_index'].reverse())
        with self.assertRaisesRegex(ValueError,'GRAPH_INDEX_ORDER'):catalog.audit()

    def test_rehashed_revision_mismatch_fails(self):
        catalog=self.graph(lambda c:c['rows']['graph'].update(revision='stale-v0'))
        with self.assertRaisesRegex(ValueError,'GRAPH_REVISION'):catalog.audit()

    def test_rehashed_set_duplicate_fails(self):
        def mutate(c):
            c['rows']['seeds']=[0,0];c['task']['datasets'][1]['stats']['item_count']=2
        catalog=self.graph(mutate)
        with self.assertRaisesRegex(ValueError,'DATA_DUPLICATE_ITEM'):catalog.audit()

    def test_source_count_cannot_hide_in_manifest(self):
        catalog=self.graph()
        catalog.sources['dataset:seeds'].entry['logical_rows']=2
        with self.assertRaisesRegex(ValueError,'DATA_LOGICAL_ROWS'):catalog.resolve('dataset:seeds').value()

    def test_incremental_arrow_logical_hash_is_recomputed(self):
        import pyarrow as pa
        fixture=build('F1-01',0,'C0',self.root/'case')
        path=self.root/'case/data_manifest.json';task=json.loads((self.root/'case/task_public.json').read_text('utf8'))
        catalog=DataCatalog(path).bind(task);expected=catalog.audit()
        source=next(iter(catalog.sources.values()))
        self.assertEqual(expected[source.entry['source_id']],digest(source.table().to_pylist()))
        source.entry['logical_content_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'DATA_LOGICAL_HASH'):source.logical_digest()

    def test_c3_cannot_forge_logical_equality_after_rehashing_physical_data(self):
        directories={c:self.root/c for c in ['C0','C1','C2','C3']}
        for c,directory in directories.items():build('F3-01',0,c,directory)
        self.assertEqual(check_group(directories)['status'],'PASS')
        directory=directories['C3'];mp=directory/'data_manifest.json';manifest=json.loads(mp.read_text('utf8'));entry=manifest['sources'][0]
        record=entry['physical_files'][0];path=directory/record['path'];payload=json.loads(path.read_text('utf8'))
        payload['nodes'][0]['value']+=1;raw=canonical(payload)+b'\n';path.write_bytes(raw)
        record.update(sha256=sha(raw),bytes=len(raw));entry['content_sha256']=digest([{k:r[k] for k in ['sha256','bytes']} for r in entry['physical_files']])
        # Rebind physical hashes as a malicious or faulty builder could, leaving its asserted logical hash unchanged.
        tp=directory/'task_public.json';task=json.loads(tp.read_text('utf8'));task['datasets'][0]['data_sha256']=entry['content_sha256']
        tp.write_bytes(canonical(task));mp.write_bytes(canonical(manifest))
        result=check_group(directories)
        self.assertEqual(result['status'],'FAIL');self.assertTrue(any('DATA_LOGICAL_HASH' in e for e in result['errors']))
