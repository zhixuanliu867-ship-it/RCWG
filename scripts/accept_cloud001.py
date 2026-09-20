#!/usr/bin/env python3
"""Cloud-profile offline tests only. This gate cannot authorize paid operations."""
import argparse,hashlib,io,json,os,platform,subprocess,sys,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rcwg_spec.common import canonical
from rcwg_api.policy import check_exec_sources,check_retained_test_sources

class Result(unittest.TextTestResult):
    def __init__(self,*a,**kw):super().__init__(*a,**kw);self.passed=[]
    def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())

def snapshot():
    result={};bad=[]
    for entry in subprocess.check_output(['git','ls-files','--stage','-z'],cwd=ROOT).split(b'\0'):
        if not entry:continue
        meta,name=entry.split(b'\t',1);mode,oid,stage=meta.split();path=ROOT/name.decode();raw=path.read_bytes()
        result[name.decode()]=hashlib.sha256(raw).hexdigest()
        if stage!=b'0' or oid.decode()!=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest():bad.append(name.decode())
    pending=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).split(b'\0')
    bad.extend(x.decode() for x in pending if x)
    return result,bad

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args();out=Path(args.output).absolute()
    if not out.is_relative_to(ROOT/'runs'):raise SystemExit('new private runs/ output required')
    out.mkdir(parents=True,exist_ok=False,mode=0o700);before,bad=snapshot();failures=[]
    if bad:failures.append('SOURCE_NOT_FULLY_INDEXED')
    if sys.platform!='linux' or sys.version_info[:3]!=(3,12,14):failures.append('LINUX_PYTHON_3_12_14_REQUIRED')
    try:check_exec_sources();retained=check_retained_test_sources()
    except Exception:retained=None;failures.append('OLD_TEST_OR_RUNTIME_BYTES_CHANGED')
    stream=io.StringIO();suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_cloud001_*.py')
    r=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
    if not r.wasSuccessful() or r.skipped or r.expectedFailures:failures.append('CLOUD_OFFLINE_TESTS')
    after,after_bad=snapshot()
    if before!=after or after_bad:failures.append('SOURCE_CHANGED')
    log=stream.getvalue().encode();(out/'unittest.log').write_bytes(log)
    report={'version':'CLOUD001_OFFLINE_ACCEPTANCE_1','status':'CLOUD001_OFFLINE_PROFILE_PASS' if not failures else 'CLOUD001_OFFLINE_PROFILE_FAIL',
        'environment':'GITHUB_CI' if os.environ.get('GITHUB_ACTIONS')=='true' else 'OWNER_WSL' if 'microsoft' in platform.release().lower() else 'OTHER_LINUX',
        'python':platform.python_version(),'kernel':platform.release(),'tests_run':r.testsRun,'passed_ids':sorted(r.passed),'failures':failures,
        'failed_ids':[t.id() for t,_ in r.failures],'error_ids':[t.id() for t,_ in r.errors],'retained_test_source_files':retained,
        'source_before_sha256':before,'source_after_sha256':after,'unittest_log_sha256':hashlib.sha256(log).hexdigest(),
        'actual_cloud_mutations':0,'actual_live_model_requests':0,'cloud_replay':'NOT_RUN_BY_THIS_GATE','cloud_live':'NOT_RUN_BY_THIS_GATE',
        'full_cloud001_accepted':False,'formal_ready':False,'formal_gate':'BLOCKED_NOT_FROZEN'}
    (out/'ACCEPTANCE.json').write_bytes(canonical(report));print(json.dumps({k:report[k] for k in ('status','environment','python','tests_run','failures')},indent=2))
    return 0 if not failures else 2

if __name__=='__main__':raise SystemExit(main())
