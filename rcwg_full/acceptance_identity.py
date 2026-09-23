"""Exact checkout, installed dependency and durable artifact identities."""
import hashlib,importlib.metadata,platform,subprocess
from pathlib import Path
from rcwg_full.evidence import ROOT,sha

BASELINE='2824ee8e7678a39b3bff2ac701ffececd50d1e81'


def git_identity():
    def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,stderr=subprocess.PIPE).decode().strip()
    return {'head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),
        'branch':git('rev-parse','--abbrev-ref','HEAD'),'baseline':BASELINE,
        'baseline_is_ancestor':subprocess.run(['git','merge-base','--is-ancestor',BASELINE,'HEAD'],cwd=ROOT).returncode==0,
        'tracked_content_clean':subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=ROOT).returncode==0,
        'untracked_source_files':git('ls-files','--others','--exclude-standard').splitlines()}


def dependencies():
    return {'python':platform.python_version(),'system':platform.system(),
        'lock_sha256':sha((ROOT/'environments/full001/requirements.lock').read_bytes()),
        'packages':{name:importlib.metadata.version(name) for name in ['pyarrow','pybind11']}}


def file_hash(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as file:
        while chunk:=file.read(1024*1024):result.update(chunk)
    return result.hexdigest()


def file_manifest(directory):
    directory=Path(directory)
    return {p.relative_to(directory).as_posix():{'sha256':file_hash(p),'bytes':p.stat().st_size}
            for p in sorted(directory.rglob('*')) if p.is_file()}
