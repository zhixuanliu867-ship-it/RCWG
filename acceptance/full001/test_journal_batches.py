"""Durable bounded batching retains every original chain event and failure."""
from pathlib import Path
from unittest.mock import patch
import os,tempfile,unittest
from rcwg_full.runtime.events import Journal,verify_journal


class JournalBatches(unittest.TestCase):
    def test_all_events_preserved_nested_boundaries_and_bounded_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=Journal(Path(tmp)/'events.jsonl','batch')
            original=os.fsync
            with patch('rcwg_full.runtime.events.os.fsync',wraps=original) as sync:
                with journal.batch():
                    for i in range(1005):
                        with journal.batch():journal.append('buffer_created',{'i':i,'payload':'x'*1200})
                        self.assertLess(journal.pending_bytes,1024*1024)
                self.assertLess(sync.call_count,10);self.assertGreaterEqual(sync.call_count,2)
                self.assertEqual(journal.pending_bytes,0)
            journal.close();events=verify_journal(journal.path)
            self.assertEqual(len(events),1005);self.assertEqual([e['payload']['i'] for e in events],list(range(1005)))

    def test_exception_still_flushes_and_sync_failure_is_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=Journal(Path(tmp)/'events.jsonl','batch')
            with self.assertRaisesRegex(ValueError,'fixture'):
                with journal.batch():journal.append('start',{});raise ValueError('fixture')
            self.assertEqual(journal.pending_bytes,0)
            with patch('rcwg_full.runtime.events.os.fsync',side_effect=OSError('disk fixture')),self.assertRaises(OSError):
                with journal.batch():journal.append('last',{})
            self.assertTrue(journal.closed)
            with self.assertRaisesRegex(RuntimeError,'CLOSED'):journal.append('never',{})
