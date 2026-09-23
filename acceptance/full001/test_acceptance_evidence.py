"""Acceptance integrity checks; synthetic journals cannot claim real coverage."""
import json,re,unittest
from pathlib import Path
from rcwg_full.evidence import ROOT,read,write
from rcwg_full.acceptance_identity import git_identity,file_hash,file_manifest
from rcwg_full.acceptance_evidence import actual_dispatches
from rcwg_full.runtime.events import Journal
from support import EvidenceDirectory


class Integrity(unittest.TestCase):
    def test_checkout_and_protected_bytes(self):
        identity=git_identity();self.assertTrue(identity['baseline_is_ancestor'])
        self.assertRegex(identity['head'],r'^[0-9a-f]{40}$');self.assertRegex(identity['tree'],r'^[0-9a-f]{40}$')
        protected=json.loads(read(ROOT/'docs/full001/INHERITED_FILE_HASHES.json'))
        self.assertEqual(len(protected),66)
        for path,expected in protected.items():self.assertEqual(file_hash(ROOT/path),expected,path)

    def test_retained_old_test_sources(self):
        frozen=json.loads(read(ROOT/'specs/full001/retained_tests_r1.json'))
        self.assertEqual(len(frozen['test_ids']),1966)
        self.assertEqual(frozen['historical_test_ids_retained'],1863)
        for name,expected in frozen['reviewed_base_test_sources'].items():
            self.assertEqual(file_hash(ROOT/'acceptance/full001'/name),expected,name)

    def test_registry_and_requirement_mapping(self):
        operators=json.loads(read(ROOT/'specs/full001/operators.json'))['operators']
        self.assertEqual(len(operators),32);self.assertEqual(sum(len(r['implementations']) for r in operators),56)
        loader=unittest.TestLoader();suite=loader.discover(str(ROOT/'acceptance/full001'))
        def flatten(item):
            if isinstance(item,unittest.TestCase):yield item.id()
            else:
                for child in item:yield from flatten(child)
        ids=set(flatten(suite));self.assertFalse(loader.errors,loader.errors)
        frozen=json.loads(read(ROOT/'specs/full001/retained_tests_r1.json'));self.assertTrue(set(frozen['test_ids'])<=ids)
        matrix=json.loads(read(ROOT/'specs/full001/requirement_tests_r1.json'))
        required={r['requirement_id'] for r in json.loads(read(ROOT/'specs/full001/requirements.json'))['requirements'] if not r['requirement_id'].startswith('EXT-')}
        self.assertEqual(set(matrix),required)
        for ident,row in matrix.items():
            for selector in row['test_selectors']:
                self.assertTrue(any(re.search(selector,t) for t in ids),(ident,selector))

    def test_started_or_failed_node_and_tampered_journal_never_cover_dispatch(self):
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        # Nested artificial input is deliberately outside the runner evidence/
        # namespace and is only supplied explicitly to the negative validator.
        case=root/'negative/evidence/test-negative';case.mkdir(parents=True)
        journal=Journal(case/'events.jsonl','negative-fixture')
        journal.append('node_started',{'operator':'scan','implementation':'sequential'})
        journal.append('node_finished',{'operator':'scan','implementation':'sequential'},status='FAILED');journal.close()
        files=file_manifest(root/'negative')
        with self.assertRaisesRegex(ValueError,'DISPATCH_EVIDENCE_MISSING'):
            actual_dispatches(root/'negative',{'test-negative':'PASS'},files,{'scan:sequential'})
        with (case/'events.jsonl').open('ab') as file:file.write(b'partial')
        with self.assertRaisesRegex(ValueError,'DISPATCH_EVIDENCE_MISSING'):
            actual_dispatches(root/'negative',{'test-negative':'PASS'},file_manifest(root/'negative'),{'scan:sequential'})
