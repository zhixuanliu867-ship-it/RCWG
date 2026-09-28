"""Independent private archive closure checks; no model service is contacted."""
from pathlib import Path
from collections import Counter
import json
import sqlite3
import unittest
import uuid
from support import EvidenceDirectory
from test_campaign_runner import slots
from rcwg_full.evidence import digest,write,canonical,read,sha
from rcwg_full.campaign.runner import CampaignRunner
from rcwg_full.campaign.sealing import seal_run,verify_seal
from rcwg_full.services.client import RequestIndex


class SealClosureTests(unittest.TestCase):
    def setUp(self):self.evidence=EvidenceDirectory('seal-'+digest(self.id())[:16]);self.root=Path(self.evidence.name)
    def tearDown(self):self.evidence.cleanup()

    def prepare(self):
        expected=slots();raw=b''.join(canonical(row)+b'\n' for row in expected)
        write(self.root/'primary.jsonl',raw)
        manifest={'schema_version':'FULL001_EXPECTED_1','spec_hash':'b'*64,
            'primary':{'file':'primary.jsonl','sha256':sha(raw),'counts':dict(Counter(row['slot_kind'] for row in expected)),'total':len(expected)},'diagnostics':{}}
        manifest['manifest_hash']=digest(manifest);write(self.root/'expected-manifest.json',manifest)
        def action(slot,attempt,deps,directory):
            write(directory/'journal.jsonl',b'{"private_sentinel":"retained"}\n')
            return {'status':'COMPLETED','protocol_fixture_only':True}
        runner=CampaignRunner(self.root/'execution',expected,manifest_hash=manifest['manifest_hash'],spec_hash=manifest['spec_hash'],
            mode='ENGINEERING_REPLAY',generate=action,execute=action)
        try:runner.run()
        finally:runner.close()
        return self.root/'expected-manifest.json'

    def test_archive_contains_raw_attempts_frozen_inputs_and_sqlite_snapshot(self):
        manifest=self.prepare();index=RequestIndex(self.root/'service-evidence'/'G0');rid=str(uuid.uuid4())
        try:index.begin(rid,{'private_fixture':'payload'});index.record(rid,'COMPLETED',{'status':'COMPLETED'})
        finally:index.close()
        before={p.relative_to(self.root).as_posix():sha(read(p)) for p in self.root.rglob('*') if p.is_file()}
        sealed=seal_run(manifest,self.root/'sealed');names=set(sealed['files'])
        self.assertEqual(sealed['expected_count'],4);self.assertEqual(sealed['attempt_count'],4)
        self.assertEqual(sum(name.endswith('/journal.jsonl') for name in names),4)
        self.assertIn('execution/campaign.sqlite3',names);self.assertIn('service-evidence/G0/'+rid+'/request.json',names)
        self.assertIn('frozen-inputs/expected-manifest.json',names)
        with sqlite3.connect(self.root/'sealed/execution/campaign.sqlite3') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],4)
        for name,value in before.items():self.assertEqual(sha(read(self.root/name)),value)
        verify_seal(self.root/'sealed/sealed-manifest.json')
        altered=next(name for name in names if name.endswith('/journal.jsonl'))
        (self.root/'sealed'/altered).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'CHANGED'):verify_seal(self.root/'sealed/sealed-manifest.json')

    def test_uncertain_physical_request_prevents_seal_even_when_worker_terminal(self):
        manifest=self.prepare();index=RequestIndex(self.root/'service-evidence'/'G0')
        try:index.begin(str(uuid.uuid4()),{'fixture':'no response'})
        finally:index.close()
        with self.assertRaisesRegex(ValueError,'SERVICE_REQUEST_NOT_RECONCILED'):seal_run(manifest,self.root/'blocked')
        self.assertFalse((self.root/'blocked/sealed-manifest.json').exists())

    def test_different_slot_definition_cannot_be_covered_by_same_slot_id(self):
        manifest=self.prepare()
        with sqlite3.connect(self.root/'execution/campaign.sqlite3') as db:
            row=json.loads(db.execute("SELECT definition FROM slots WHERE id='generation'").fetchone()[0]);row['trial_label']=29
            db.execute("UPDATE slots SET definition=? WHERE id='generation'",(canonical(row).decode(),))
        with self.assertRaisesRegex(ValueError,'SEAL_SLOT_BINDING'):seal_run(manifest,self.root/'changed')
