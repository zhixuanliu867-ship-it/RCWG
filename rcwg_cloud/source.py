"""An image source closure is separate from the OCI image digest."""
from pathlib import Path
import hashlib,json
from .transport import CloudError

RUNTIME_DIRS=('rcwg_boot','rcwg_spec','rcwg_exec','rcwg_api','rcwg_cloud','specs','prompts','configs')
RUNTIME_FILES=('pyproject.toml','uv.lock','containers/cloud001/Dockerfile')

def verify(root,expected_sha256):
    root=Path(root);raw=(root/'IMAGE_SOURCE.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha256:raise CloudError('IMAGE_SOURCE_MANIFEST_HASH')
    value=json.loads(raw)
    if type(value) is not dict or set(value)!={'version','git_commit','files'} or value['version']!='CLOUD001_IMAGE_SOURCE_1':raise CloudError('IMAGE_SOURCE_SHAPE')
    files=value['files'];actual=set()
    if type(files) is not dict or not files:raise CloudError('IMAGE_SOURCE_EMPTY')
    for p in root.rglob('*'):
        if p.is_symlink():raise CloudError('IMAGE_SOURCE_SYMLINK')
        if p.is_file() and p!=root/'IMAGE_SOURCE.json':actual.add(p.relative_to(root).as_posix())
    if actual!=set(files):raise CloudError('IMAGE_SOURCE_FILE_SET')
    for name,want in files.items():
        p=root/name
        if not p.resolve().is_relative_to(root.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=want:raise CloudError('IMAGE_SOURCE_FILE_CHANGED')
    return {'status':'IMAGE_SOURCE_BYTES_VERIFIED','manifest_sha256':expected_sha256,'git_commit':value['git_commit'],'files':len(files),'oci_image_digest_verified_here':False}
