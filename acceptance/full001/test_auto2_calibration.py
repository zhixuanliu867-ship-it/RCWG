"""Offline evidence-boundary fixtures, never real host calibration evidence."""
import json,unittest
from rcwg_full.evidence import write,read,digest,sha
from rcwg_full.auto2.calibration import validate_auto2_calibration
from rcwg_full.runtime.calibration import REQUIRED,validate_calibration
from rcwg_full.auto2.formal import phase_affordable
import test_auto2


class Auto2Calibration(unittest.TestCase):
    setUp=test_auto2.Auto2Control.setUp
    def package(self):
        identity={'offline_fixture_identity':True}
        write(self.root/'authority.json',self.auth);raw_hash=write(self.root/'raw.json',{'fixture':True})
        checks={}
        for name in REQUIRED:
            value={'check':name,'status':'PASS','runtime_identity_hash':digest(identity),'environment':'REAL_AUTO2_HOST','raw_files':{'raw.json':raw_hash}}
            if name=='sampler_overhead':value.update(sample_interval_ms=100,families={f:{'pairs':20,'ci95_upper':.02,'off_batch_min_ns':200_000_000} for f in ['cpu','short','graph','stream','shared','disk']})
            file=name+'.json';checks[name]={'file':file,'sha256':write(self.root/file,value)}
        package={'revision':'AUTO2_CALIBRATION_1','runtime_identity':identity,'authority_file':'authority.json',
                 'authority_hash':digest(self.auth),'manual_signature':False,'checks':checks}
        path=self.root/'calibration.json';write(path,package);return path,identity,package
    def replace_check(self,path,package,name,change):
        file=self.root/package['checks'][name]['file'];value=json.loads(read(file));change(value);file.write_text(json.dumps(value))
        package['checks'][name]['sha256']=sha(read(file));path.write_text(json.dumps(package))
    def test_automatic_evidence_does_not_require_or_fabricate_auditor_signature(self):
        path,identity,package=self.package()
        self.assertEqual(validate_calibration(path,identity),sha(read(path)));self.assertNotIn('audit_receipt',package)
    def test_failed_overhead_cannot_be_promoted_by_pass_label(self):
        path,identity,package=self.package()
        self.replace_check(path,package,'sampler_overhead',lambda e:e['families']['graph'].update(ci95_upper=.031))
        with self.assertRaisesRegex(PermissionError,'OVERHEAD'):validate_calibration(path,identity)
    def test_inconclusive_short_batch_cannot_admit_formal_profile(self):
        path,identity,package=self.package()
        self.replace_check(path,package,'sampler_overhead',lambda e:e['families']['short'].update(off_batch_min_ns=99_999_999))
        with self.assertRaisesRegex(PermissionError,'OVERHEAD'):validate_calibration(path,identity)
    def test_scope_cannot_use_another_root_calibration(self):
        path,identity,package=self.package()
        with self.assertRaisesRegex(PermissionError,'AUTHORITY'):validate_auto2_calibration(path,identity,authority_hash='0'*64)
    def test_raw_evidence_change_invalidates_calibration(self):
        path,identity,package=self.package();(self.root/'raw.json').write_text('{}')
        with self.assertRaisesRegex(PermissionError,'RAW_HASH'):validate_calibration(path,identity)
    def test_new_boot_or_profile_invalidates_calibration(self):
        path,identity,package=self.package()
        with self.assertRaisesRegex(PermissionError,'RUNTIME'):validate_calibration(path,{'other_boot':True})
    def test_formal_block_respects_shared_later_phase_allocation(self):
        scope=self.state.derive_scope(stage='B_DEVELOPMENT',identity=self.identity,limits={'G':1},ceiling_microusd=50_000_000,expires_at=self.expiry)
        self.state.reserve(scope,'spent','G',50_000_000,self.identity)
        self.assertTrue(self.state.affordable(1));self.assertFalse(phase_affordable(self.state,1))
