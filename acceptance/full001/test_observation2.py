"""BOOT_ONLY adversarial checks for the versioned observation path."""
import errno
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from rcwg_full.evidence import digest,canonical
from rcwg_full.runtime.observation import PROFILE,Lifetime,validate_observation
from rcwg_full.runtime.block_journal import BlockJournal,MAX_LINE
from rcwg_full.runtime.events import Journal,verify_journal,iter_journal,journal_summary
from rcwg_full.runtime.artifacts import ArtifactStore
from rcwg_full.runtime.worker import finalize


class Observation2(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def journal(self):return BlockJournal(self.root/'events.jsonl','run')
    def store(self,journal):return ArtifactStore(self.root/'artifacts','run',journal,observation_profile=PROFILE)

    def test_profile_rejects_unfrozen_options(self):
        with self.assertRaises(ValueError):validate_observation({**PROFILE,'python_heap_inventory':'APPROXIMATE'})

    def test_block_roundtrip_multiple_blocks_and_stream_hash(self):
        journal=self.journal()
        with journal.batch():
            for i in range(4000):journal.append('record',{'i':i,'text':'中'*20},node_instance='n')
        seal=journal.seal(self.root/'seal.json')
        events=verify_journal(journal.path,expected_sha256=seal['journal_sha256'],run_id='run')
        self.assertEqual([e['payload']['i'] for e in events],list(range(4000)))
        self.assertEqual(len({e['event_id'] for e in events}),4000)
        self.assertTrue(all(len(line)<=MAX_LINE for line in journal.path.read_bytes().splitlines()))
        self.assertEqual(journal_summary(journal.path)['event_count'],4000)

    def test_rehashed_duplicate_sequence_and_clock_are_rejected(self):
        journal=self.journal()
        with journal.batch():journal.append('x',{});journal.append('y',{})
        journal.close();raw=journal.path.read_bytes().splitlines();block=json.loads(raw[1])
        for field,value,error in [(0,0,'CHAIN'),(1,-1,'CLOCK')]:
            broken=json.loads(raw[1]);broken['rows'][1][field]=value
            broken['block_hash']=digest({k:v for k,v in broken.items() if k!='block_hash'})
            journal.path.write_bytes(raw[0]+b'\n'+canonical(broken)+b'\n')
            with self.assertRaisesRegex(ValueError,error):journal_summary(journal.path)

    def test_truncation_tamper_and_wrong_identity(self):
        journal=self.journal();journal.append('x',{});journal.close();raw=journal.path.read_bytes()
        for broken in [raw[:-1],raw.replace(b'"x"',b'"z"')]:
            journal.path.write_bytes(broken)
            with self.assertRaises(ValueError):journal_summary(journal.path)
        journal.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'IDENTITY'):journal_summary(journal.path,run_id='other')
        with self.assertRaisesRegex(ValueError,'HASH'):journal_summary(journal.path,expected_sha256='0'*64)

    def test_legacy_duplicate_id_uses_disk_index(self):
        journal=Journal(self.root/'legacy.jsonl','run');journal.append('x',{});journal.append('y',{});journal.close()
        events=verify_journal(journal.path);events[1]['event_id']=events[0]['event_id']
        events[1]['event_hash']=digest({k:v for k,v in events[1].items() if k!='event_hash'})
        journal.path.write_bytes(b''.join(canonical(event)+b'\n' for event in events))
        with self.assertRaisesRegex(ValueError,'IDENTITY'):journal_summary(journal.path)

    def test_successful_short_writes_are_completed(self):
        journal=self.journal();real=os.write
        with patch('rcwg_full.runtime.block_journal.os.write',side_effect=lambda fd,data:real(fd,data[:7])):
            journal.append('x',{'payload':'0123456789'*20})
        journal.seal(self.root/'seal.json');self.assertEqual(journal_summary(journal.path)['event_count'],1)

    def test_write_failures_never_seal(self):
        for error in [OSError(errno.EFBIG,'injected'),OSError(errno.ENOSPC,'injected'),None]:
            with self.subTest(error=error),tempfile.TemporaryDirectory() as directory:
                journal=BlockJournal(Path(directory)/'events','run')
                with patch('rcwg_full.runtime.block_journal.os.write',side_effect=error,return_value=0):
                    with self.assertRaises(OSError):journal.append('x',{})
                with self.assertRaises(ValueError):journal.seal(Path(directory)/'seal')
                self.assertFalse((Path(directory)/'seal').exists())

    def test_nested_alias_and_cross_alias_lease_are_preserved(self):
        journal=self.journal();store=self.store(journal);shared=[object(),{'payload':321987}]
        a=store.register({'first':shared},{'kind':'X'},'a');b=store.register({'second':shared},{'kind':'X'},'b')
        self.assertTrue(a.python_ids&b.python_ids);self.assertFalse(store.buffers)
        store.acquire(b,'reader')
        with self.assertRaisesRegex(ValueError,'LAST_USE'):store.release(a)
        store.drop_lease(b,'reader')
        with self.assertRaisesRegex(ValueError,'LIVE_ALIAS'):store.release(a)
        store.drop_view(b);store.release(a)
        self.assertFalse(a.python_ids);self.assertFalse(a.python_roots)
        journal.close()

    def test_parent_identity_is_retained_until_view_is_dropped(self):
        journal=self.journal();store=self.store(journal);value=[{'x':9876}]
        a=store.register(value,{'kind':'X'},'a');b=store.register([],{'kind':'X'},'b',parents=[a])
        self.assertTrue(a.python_ids<=b.python_ids);self.assertTrue(any(root is value for root in b.python_roots))
        store.drop_view(a);self.assertTrue(b.python_roots);store.drop_view(b);journal.close()

    def test_main_profile_omits_deep_heap_bytes_but_keeps_actual_copy(self):
        journal=self.journal();store=self.store(journal)
        a=store.register([{'x':i} for i in range(20000)],{'kind':'X'},'a');store.copied(b'12345','a',scope='ENCODE')
        store.drop_view(a);metrics=store.lifetime_metrics();journal.close()
        self.assertEqual(metrics['registered_python_heap']['status'],'NOT_MEASURED')
        self.assertIsNone(metrics['registered_combined']['peak_bytes']);self.assertEqual(metrics['instrumented_copy_bytes'],5)
        self.assertLess(journal.path.stat().st_size,4096)

    def test_arrow_shared_lifetime_and_cleanup_failure(self):
        import pyarrow as pa
        journal=self.journal();store=self.store(journal);table=pa.table({'x':[1,2,3]})
        a=store.register(table,{'kind':'Table'},'a');b=store.register(table.slice(1),{'kind':'Table'},'b')
        self.assertEqual(a.buffer_ids,b.buffer_ids)
        with self.assertRaisesRegex(ValueError,'LIVE_ALIAS'):store.release(a)
        store.drop_view(b);store.release(a);self.assertFalse(store.buffers)
        self.assertEqual(store.lifetime_metrics()['registered_buffer_peak_bytes'],24)
        disk=store.register(table,{'kind':'Table'},'d',storage='disk');store.seal(disk)
        with patch.object(Path,'unlink',side_effect=OSError(errno.EACCES,'injected')):
            with self.assertRaises(OSError):store.release(disk)
        self.assertEqual(disk.release_status,'LIVE');store.release(disk);journal.close()

    def test_online_integral_matches_release_before_create_at_same_time(self):
        metric=Lifetime();metric.change(10,20);metric.change(20,30);metric.change(20,-20);metric.change(30,-30)
        self.assertEqual(metric.snapshot(40),{'peak_bytes':30,'byte_seconds':500/1e9})
        # Snapshot does not commit an equal-time group prematurely.
        other=Lifetime();other.change(1,10);other.snapshot(2);other.change(2,20);other.change(2,-10)
        self.assertEqual(other.snapshot(3)['peak_bytes'],20)

    def test_primary_fault_survives_closed_journal(self):
        journal=self.journal();journal.close();primary={'code':'ORIGINAL_EFBIG','attribution':'facility'}
        result={'run_id':'run','terminal_status':'INFRA_FAILURE','failure':primary,'secondary_failures':[]}
        finalize({'run_id':'run'},self.root,result,journal,None,None,1)
        report=json.loads((self.root/'worker-report.json').read_text())
        self.assertEqual(report['failure'],primary);self.assertEqual(report['journal_status'],'UNSEALED')
        self.assertEqual(report['secondary_failures'][0]['stage'],'JOURNAL_FINALIZE')
        self.assertFalse((self.root/'journal-seal.json').exists())

    def test_seal_and_report_failure_emit_bounded_emergency(self):
        journal=self.journal();result={'run_id':'run','terminal_status':'COMPLETED','failure':None,'secondary_failures':[]}
        with patch.object(journal,'seal',side_effect=OSError(errno.ENOSPC,'seal')):
            with patch('rcwg_full.runtime.worker.write',side_effect=OSError(errno.ENOSPC,'report')):
                with patch('rcwg_full.runtime.worker.os.write',return_value=1) as emergency:
                    # Close first so the patched os.write cannot emulate endless
                    # one-byte journal writes and hides no original write error.
                    journal.close();finalize({'run_id':'run'},self.root,result,journal,None,None,1)
                    self.assertLess(len(emergency.call_args.args[1]),8300)
        self.assertEqual(result['terminal_status'],'INFRA_FAILURE');self.assertEqual(result['journal_status'],'UNSEALED')

    def test_seal_failure_preserves_independent_worker_report(self):
        journal=self.journal();result={'run_id':'run','terminal_status':'COMPLETED','failure':None,'secondary_failures':[]}
        with patch.object(journal,'seal',side_effect=OSError(errno.ENOSPC,'seal')):
            finalize({'run_id':'run'},self.root,result,journal,None,None,1)
        report=json.loads((self.root/'worker-report.json').read_text())
        self.assertEqual(report['terminal_status'],'INFRA_FAILURE')
        self.assertEqual(report['failure']['detail'],'[Errno 28] seal')
        self.assertEqual(report['journal_status'],'UNSEALED');self.assertFalse((self.root/'journal-seal.json').exists())
