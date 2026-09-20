from pathlib import Path
import hashlib,json,tempfile,unittest
import importlib.util,subprocess,tarfile
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

class CloudBuildArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir()
        (self.repo/'rcwg_cloud').mkdir();(self.repo/'configs/cloud001').mkdir(parents=True)
        (self.repo/'rcwg_cloud/demo.py').write_text('public = True\n');(self.repo/'configs/cloud001/demo.json').write_text('{}\n')
        (self.repo/'.gitignore').write_text('runs/\n');(self.repo/'runs').mkdir();(self.repo/'runs/private.json').write_text('PRIVATE_CANARY')
        def git(*a):subprocess.run(['git',*a],cwd=self.repo,check=True,capture_output=True)
        git('init');git('add','.');git('-c','user.name=Offline Test','-c','user.email=offline@example.invalid','commit','-m','fixture')
        spec=importlib.util.spec_from_file_location('cloud_context_test',Path(__file__).resolve().parents[1]/'scripts/cloud001_build_context.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
    def test_every_file_parent_precedes_it_for_strict_gcs_fetcher(self):
        out=self.root/'source.tar.gz';proof=self.module.build_context(self.repo,out);target=self.root/'strict-extract';target.mkdir()
        with tarfile.open(out) as t:
            for member in t:
                path=target/member.name
                if member.isdir():path.mkdir(mode=member.mode,parents=False)
                else:
                    self.assertTrue(path.parent.is_dir(),member.name)
                    with path.open('xb') as f:f.write(t.extractfile(member).read())
        self.assertEqual(verify(target,proof['image_source_sha256'])['status'],'IMAGE_SOURCE_BYTES_VERIFIED')
        self.assertFalse((target/'runs').exists());self.assertNotIn('PRIVATE_CANARY',str(proof))
    def test_identical_clean_commit_produces_identical_archive(self):
        a=self.module.build_context(self.repo,self.root/'one.tgz');b=self.module.build_context(self.repo,self.root/'two.tgz')
        self.assertEqual(a['source_archive_sha256'],b['source_archive_sha256'])

if __name__=='__main__':unittest.main()
