import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from rcwg_full.runtime.artifacts import ArtifactStore
from rcwg_full.runtime.events import Journal,verify_journal
from support import EvidenceDirectory


class Artifacts(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        self.pa=pa;self.tmp=EvidenceDirectory(self.id());self.root=Path(self.tmp.name)
        self.journal=Journal(self.root/'events.jsonl','test-run')
        self.store=ArtifactStore(self.root/'artifacts','test-run',self.journal)
        self.table=pa.table({'id':[1,2,3],'text':['a','中',None]})
    def tearDown(self):self.journal.close();self.tmp.cleanup()
    def register(self,value=None,**kwargs):return self.store.register(self.table if value is None else value,{'kind':'Table','domain':'rows'},'n1',**kwargs)

    def test_views_share_actual_buffers_and_copy_does_not(self):
        a=self.register();v=self.register(self.table.slice(1));c=self.register(self.pa.Table.from_pylist(self.table.to_pylist()))
        self.assertEqual(a.buffer_ids,v.buffer_ids);self.assertFalse(a.buffer_ids&c.buffer_ids)
        with self.assertRaisesRegex(ValueError,'LIVE_ALIAS'):self.store.release(a)
        self.store.acquire(v,'reader')
        with self.assertRaisesRegex(ValueError,'LIVE_VIEW_LEASE'):self.store.drop_view(v)
        self.store.drop_lease(v,'reader');self.store.drop_view(v);self.store.release(a);self.store.release(c)
        self.assertTrue(all(b['value'] is None and b['released_ns'] is not None for b in self.store.buffers.values()))

    def test_last_view_releases_buffer(self):
        a=self.register();v=self.register(self.table.slice(0,1));self.store.drop_view(a);self.store.drop_view(v)
        self.assertFalse(self.store.addresses);self.assertTrue(all(b['released_ns'] for b in self.store.buffers.values()))

    def test_scalar_leases_and_cross_run_capability(self):
        a=self.register({'x':3});self.store.acquire(a,'branch-capture')
        with self.assertRaisesRegex(ValueError,'LAST_USE'):self.store.release(a)
        a.run_id='different'
        with self.assertRaisesRegex(ValueError,'CAPABILITY'):self.store.load(a)
        a.run_id='test-run';self.store.drop_lease(a,'branch-capture');self.store.release(a)

    def test_disk_seal_releases_memory_and_roundtrips_batches(self):
        for format in ['arrow_ipc','parquet']:
            with self.subTest(format=format):
                a=self.register(storage='disk',format=format);old=a.buffer_ids.copy();self.store.seal(a)
                self.assertIsNone(a.value);self.assertTrue(all(self.store.buffers[b]['value'] is None for b in old))
                self.assertEqual(self.pa.Table.from_batches(list(self.store.batches(a,2))).to_pylist(),self.table.to_pylist())
                self.assertTrue(a.path.name.startswith(a.content_sha256));self.assertEqual(self.store.load(a).to_pylist(),self.table.to_pylist())
                path=a.path;self.store.release(a);self.assertFalse(path.exists())

    def test_hash_tamper_and_cleanup_failure_preserve_lifetime(self):
        a=self.register(storage='disk');self.store.seal(a)
        with patch.object(Path,'unlink',side_effect=PermissionError('injected')):
            with self.assertRaises(PermissionError):self.store.release(a)
        self.assertEqual(a.release_status,'LIVE');self.assertTrue(all(self.store.buffers[b]['released_ns'] is None for b in a.buffer_ids))
        with a.path.open('ab') as f:f.write(b'bad')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_HASH'):self.store.load(a)
        self.store.release(a)

    def test_failed_commit_never_seals(self):
        a=self.register(storage='disk')
        with patch('rcwg_full.runtime.artifacts.os.rename',side_effect=OSError('injected')):
            with self.assertRaises(OSError):self.store.seal(a)
        self.assertIsNone(a.sealed_ns);self.assertIsNotNone(a.value)
        self.assertTrue(list(self.store.directory.glob('*.partial')))
        self.journal.close();self.assertEqual(verify_journal(self.journal.path)[-1]['event_kind'],'artifact_commit_failed')

    def test_half_open_interval_integration_counts_unique_buffers(self):
        a=self.register();v=self.register(self.table.slice(1));ids=sorted(a.buffer_ids)
        for b in self.store.buffers.values():b.update(created_ns=10,released_ns=20)
        capacity=sum(self.store.buffers[b]['capacity_bytes'] for b in ids)
        m=self.store.lifetime_metrics(30)
        self.assertEqual(m['registered_buffer_peak_bytes'],capacity);self.assertAlmostEqual(m['registered_buffer_byte_seconds'],capacity*10/1e9)
        self.assertIsNone(m['worker_cgroup_memory_peak'])
