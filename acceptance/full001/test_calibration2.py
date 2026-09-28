"""BOOT_ONLY admission rejection checks; labels cannot replace measured proof."""
import json
import unittest
from rcwg_full.evidence import read,write,sha,digest
from rcwg_full.runtime.observation import PROFILE
from rcwg_full.runtime.calibration import validate_calibration
import test_auto2_calibration


class Calibration2(unittest.TestCase):
    setUp=test_auto2_calibration.Auto2Calibration.setUp
    replace_check=test_auto2_calibration.Auto2Calibration.replace_check
    def package(self):
        path,identity,package=test_auto2_calibration.Auto2Calibration.package(self)
        identity['observation_profile']=PROFILE;package['runtime_identity']=identity;package['revision']='AUTO2_CALIBRATION_2'
        protocol={'runtime_identity_hash':digest(identity),'pairs_per_family':20,'pass_rule':'CI95_UPPER_LE_0.03','repeat_until_pass':False,'frozen_monotonic_ns':10}
        package.update(protocol_file='protocol.json',protocol_sha256=write(self.root/'protocol.json',protocol),campaign_start_file='start.json')
        write(self.root/'start.json',{'monotonic_ns':20,'runtime_identity_hash':digest(identity)})
        for name,entry in package['checks'].items():
            file=self.root/entry['file'];value=json.loads(read(file));value['runtime_identity_hash']=digest(identity)
            if name=='sampler_overhead':value['families']['graph_scale']={'pairs':20,'ci95_upper':.02,'off_batch_min_ns':200_000_000}
            if name=='full_worker_integration':value['actual_graph_scale']={'status':'PASS','observation_profile':PROFILE,
                'input_registration_observed':True,'release_observed':True,'journal_sealed':True,'answer_independently_verified':True,
                'task_sha256':'a'*64,'data_manifest_sha256':'b'*64,'plan_sha256':'c'*64}
            file.write_text(json.dumps(value));entry['sha256']=sha(read(file))
        path.write_text(json.dumps(package));return path,identity,package
    def test_versioned_scale_protocol_is_bound(self):
        path,identity,package=self.package();self.assertEqual(validate_calibration(path,identity),sha(read(path)))
    def test_small_only_or_missing_release_cannot_qualify(self):
        path,identity,package=self.package()
        self.replace_check(path,package,'full_worker_integration',lambda value:value['actual_graph_scale'].update(release_observed=False))
        with self.assertRaisesRegex(PermissionError,'GRAPH_SCALE'):validate_calibration(path,identity)
    def test_graph_scale_ci_above_three_percent_cannot_qualify(self):
        path,identity,package=self.package()
        self.replace_check(path,package,'sampler_overhead',lambda value:value['families']['graph_scale'].update(ci95_upper=.03001))
        with self.assertRaisesRegex(PermissionError,'OVERHEAD'):validate_calibration(path,identity)
    def test_protocol_frozen_after_campaign_start_rejected(self):
        path,identity,package=self.package();p=self.root/'protocol.json';protocol=json.loads(read(p));protocol['frozen_monotonic_ns']=21
        p.write_text(json.dumps(protocol));package['protocol_sha256']=sha(read(p));path.write_text(json.dumps(package))
        with self.assertRaisesRegex(PermissionError,'PREREGISTRATION'):validate_calibration(path,identity)
