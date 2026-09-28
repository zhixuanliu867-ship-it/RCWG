from pathlib import Path
import json
import stat
import unittest
import zipfile
from rcwg_full.evidence import digest,sha,write,read
from rcwg_full.data.snapshots import snapshot,extract_zip
from rcwg_full.campaign.forecast import forecast
from support import EvidenceDirectory


class SnapshotForecastTests(unittest.TestCase):
    def setUp(self):self.evidence=EvidenceDirectory('source-'+digest(self.id())[:16]);self.root=Path(self.evidence.name)
    def tearDown(self):self.evidence.cleanup()

    def test_local_hash_dedup_resume_and_license_unknown(self):
        raw='原始 Unicode 🙂 source'.encode();source=self.root/'input';source.write_bytes(raw)
        target=self.root/'snapshot';r=snapshot(source,target,expected_sha256=sha(raw),max_bytes=1024,upstream_revision='fixture')
        self.assertEqual(r['status'],'HASH_VERIFIED');self.assertFalse(r['redistribution_authorized'])
        self.assertEqual(snapshot(source,target,expected_sha256=sha(raw),max_bytes=1024,upstream_revision='fixture',resume=True),r)
        (target/'source.snapshot').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SNAPSHOT_CHANGED'):snapshot(source,target,expected_sha256=sha(raw),max_bytes=1024,upstream_revision='fixture',resume=True)

    def test_partial_local_snapshot_resumes_bound_prefix(self):
        raw=b'0123456789'*100;source=self.root/'input';source.write_bytes(raw);target=self.root/'partial'
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):snapshot(source,target,expected_sha256='0'*64,max_bytes=2000,upstream_revision='fixture')
        self.assertTrue((target/'source.partial').exists());self.assertFalse((target/'source.snapshot').exists())
        with self.assertRaisesRegex(ValueError,'RESUME_BINDING'):snapshot(source,target,expected_sha256=sha(raw),max_bytes=2000,upstream_revision='fixture',resume=True)
        # Construct an interrupted, already declared correct transfer, not a
        # success synthesized from a previously wrong expected checksum.
        target=self.root/'interrupted';target.mkdir()
        write(target/'declaration.json',{'revision':'FULL001_SOURCE_SNAPSHOT_1','source':str(source),'expected_sha256':sha(raw),'max_bytes':2000,'upstream_revision':'fixture','license_record':None})
        (target/'source.partial').write_bytes(raw[:100])
        result=snapshot(source,target,expected_sha256=sha(raw),max_bytes=2000,upstream_revision='fixture',resume=True)
        self.assertEqual(result['bytes'],1000);self.assertEqual((target/'source.snapshot').read_bytes(),raw)

    def test_remote_source_is_explicit_and_no_download_occurs(self):
        with self.assertRaisesRegex(PermissionError,'NETWORK_REQUIRED'):
            snapshot('https://example.invalid/data',self.root/'remote',expected_sha256='a'*64,max_bytes=10,upstream_revision='unknown')
        self.assertFalse((self.root/'remote/source.partial').exists())

    def test_zip_traversal_symlink_and_capacity_rejected_before_extract(self):
        for index,name in enumerate(['../escape','C:/escape','a\\escape','/escape']):
            archive=self.root/f'bad{index}.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr(name,b'x')
            # Windows ZipInfo normalizes separators while creating archives;
            # construct the malformed wire name to test the actual reader.
            if '\\' in name:archive.write_bytes(archive.read_bytes().replace(name.replace('\\','/').encode(),name.encode()))
            with self.assertRaises(ValueError):extract_zip(archive,self.root/f'out{index}',expected_sha256=sha(read(archive)),max_files=2,max_uncompressed_bytes=10)
            self.assertFalse((self.root/f'out{index}').exists())
        archive=self.root/'link.zip';info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
        with zipfile.ZipFile(archive,'w') as z:z.writestr(info,'/etc/passwd')
        with self.assertRaisesRegex(ValueError,'SPECIAL_FILE'):extract_zip(archive,self.root/'link-out',expected_sha256=sha(read(archive)),max_files=2,max_uncompressed_bytes=100)
        archive=self.root/'good.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('nested/a',b'abc');z.writestr('nested/b',b'abc')
        r=extract_zip(archive,self.root/'good',expected_sha256=sha(read(archive)),max_files=2,max_uncompressed_bytes=6)
        self.assertEqual(r['logical_duplicate_content_groups'][sha(b'abc')],['nested/a','nested/b'])

    def test_forecast_stage_counts_cost_and_unknown_categories(self):
        slots=[{'slot_id':'a','slot_kind':'generation','generator':'G0','protocol':'P0','ledger_role':'PRIMARY','experiment_id':'E1'},
               {'slot_id':'b','slot_kind':'generation','generator':'G0','protocol':'P1','ledger_role':'PRIMARY','experiment_id':'E1'}]
        r=forecast(slots);self.assertEqual(r['G_requests_upper'],3);self.assertIsNone(r['aggregate_cost_usd'])
        self.assertTrue(all(row['cost_usd_upper'] is None for row in r['generation']))
        price={'as_of':'fixture-date','source':'fixture','input_usd_per_million':'1','output_usd_per_million':'2'}
        r=forecast(slots,price_snapshots={'G0':price});p0=next(row for row in r['generation'] if row['protocol']=='P0')
        self.assertEqual(p0['cost_usd_upper'],'0.045056');self.assertTrue(all(row['cost_usd'] is None for row in r['other_categories']))
        with self.assertRaisesRegex(ValueError,'DEVELOPMENT_USAGE_ONLY'):forecast(slots,development_usage=[{'split':'test','origin':'PROVIDER_USAGE'}])
        write(self.root/'forecast.json',r)
