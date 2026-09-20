from pathlib import Path
import hashlib,json,tempfile,unittest
from rcwg_cloud.source import verify
from rcwg_cloud.transport import CloudError
from rcwg_spec.common import canonical

class CloudSourceClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'runtime.py').write_bytes(b'print("offline")\n')
        self.value={'version':'CLOUD001_IMAGE_SOURCE_1','git_commit':'a'*40,'files':{'runtime.py':hashlib.sha256((self.root/'runtime.py').read_bytes()).hexdigest()}}
        raw=canonical(self.value);(self.root/'IMAGE_SOURCE.json').write_bytes(raw);self.sha=hashlib.sha256(raw).hexdigest()
    def test_complete_bytes_verified_separately_from_oci_image(self):
        r=verify(self.root,self.sha);self.assertEqual(r['files'],1);self.assertFalse(r['oci_image_digest_verified_here'])
    def test_extra_file_rejected_even_with_expected_named_nested_manifest(self):
        (self.root/'extra').mkdir();(self.root/'extra/IMAGE_SOURCE.json').write_bytes(b'{}')
        with self.assertRaises(CloudError):verify(self.root,self.sha)
    def test_changed_bytes_or_external_source_hash_rejected(self):
        with self.assertRaises(CloudError):verify(self.root,'b'*64)
        (self.root/'runtime.py').write_bytes(b'changed')
        with self.assertRaises(CloudError):verify(self.root,self.sha)
    def test_symlink_is_not_source(self):
        (self.root/'alias').symlink_to(self.root/'runtime.py')
        with self.assertRaises(CloudError):verify(self.root,self.sha)

if __name__=='__main__':unittest.main()
