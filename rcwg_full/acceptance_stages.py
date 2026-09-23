"""stdlib-only acceptance stage records. Incomplete stages are never replayed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def save(path,value):
    with Path(path).open('x',encoding='utf8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())


def files(directory):
    result={}
    for path in directory.rglob('*'):
        if path.is_symlink():raise ValueError('STAGE_SYMLINK')
        if path.is_file() and path!=directory/'stage.json':
            with path.open('rb') as f:result[path.relative_to(directory).as_posix()]=hashlib.file_digest(f,'sha256').hexdigest()
    return result


def run_stage(out,name,command,*,source_hash,cwd,resume=False,timeout=7200,expected_report=None):
    directory=Path(out)/name
    common={'name':name,'command':command,'source_hash':source_hash,'expected_report':expected_report}
    if directory.exists():
        if not resume:return {**common,'status':'BLOCKED','exit_code':2,'blocker':'STAGE_ALREADY_EXISTS'}
        if not (directory/'stage.json').is_file():
            return {**common,'status':'BLOCKED','exit_code':2,'blocker':'INCOMPLETE_STAGE_REQUIRES_RECONCILIATION','launch_performed':False}
        try:
            prior=json.loads((directory/'stage.json').read_text('utf8'))
            if any(prior.get(k)!=v for k,v in common.items()):raise ValueError('STAGE_RESUME_IDENTITY')
            if files(directory)!=prior['files']:raise ValueError('STAGE_RESUME_ARTIFACT')
            if prior['exit_code'] not in {0,1,2,3} or prior.get('status') not in {'PASS','FAIL','BLOCKED'}:raise ValueError('STAGE_RESULT_SHAPE')
            return prior
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return {**common,'status':'BLOCKED','exit_code':2,'blocker':str(exc),'launch_performed':False}
    directory.mkdir(mode=0o700);start=time.time_ns();error=None
    try:
        with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
            result=subprocess.run(command,cwd=cwd,stdout=stdout,stderr=stderr,timeout=timeout)
        exit_code=result.returncode;status='PASS' if exit_code==0 else 'FAIL'
    except subprocess.TimeoutExpired:
        # subprocess.run stops its immediate child. Descendant state requires
        # explicit reconciliation; a resume must not launch a second process.
        exit_code=2;status='BLOCKED';error='STAGE_TIMEOUT_DESCENDANTS_REQUIRE_RECONCILIATION'
    except OSError as exc:exit_code=2;status='BLOCKED';error=type(exc).__name__+':'+str(exc)
    record={**common,'status':status,'exit_code':exit_code,'blocker':error,'started_unix_ns':start,
        'finished_unix_ns':time.time_ns(),'files':files(directory)}
    save(directory/'stage.json',record);return record
