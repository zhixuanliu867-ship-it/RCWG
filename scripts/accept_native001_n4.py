"""N4 offline gate; refuses to label simulated tests as host calibration."""
from pathlib import Path
import argparse,io,json,platform,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_native.evidence import ROOT,bootstrap,read,write,sha
from rcwg_api.policy import source_snapshot,check_staged_snapshot
def flatten(s):
    for t in s:
        if isinstance(t,unittest.TestSuite):yield from flatten(t)
        else:yield t
class Result(unittest.TextTestResult):
    def __init__(self,*a,**k):super().__init__(*a,**k);self.passed=[]
    def addSuccess(self,t):super().addSuccess(t);self.passed.append(t.id())
def main(build,output):
    out=bootstrap(output)
    if platform.system()!='Linux' or platform.python_version()!='3.12.14':raise ValueError('TARGET_REQUIRED')
    before=source_snapshot();check_staged_snapshot(before)
    manifest=read(Path(build)/'N4_BUILD.json')
    for p,h in manifest['source'].items():
        if sha((ROOT/p).read_bytes())!=h:raise ValueError('BUILD_SOURCE_MISMATCH')
    for b in manifest['binaries'].values():
        if sha((Path(build)/b['name']).read_bytes())!=b['sha256']:raise ValueError('BINARY_MISMATCH')
    sys.path.insert(0,str(ROOT/'native001_n4_tests'));import test_n4_protocol
    test_n4_protocol.BUILD=Path(build).absolute()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'native001_n4_tests'));ids=sorted(t.id() for t in flatten(suite));frozen=read(ROOT/'specs/native001n4/FROZEN_TESTS.json')
    if ids!=frozen['ids']:raise ValueError('N4_TEST_IDS_CHANGED')
    for p,h in frozen['sources'].items():
        if sha((ROOT/p).read_bytes())!=h:raise ValueError('N4_TEST_SOURCE_CHANGED')
    write(out/'EXPECTED_TESTS.json',frozen);log=io.StringIO();r=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
    write(out/'unittest.log',log.getvalue().encode());write(out/'PASSED_TEST_IDS.json',r.passed)
    if source_snapshot()!=before:raise ValueError('SOURCE_CHANGED')
    result={'status':'N4_OFFLINE_PASS' if r.wasSuccessful() and not r.skipped else 'FAIL','tests_run':r.testsRun,'passed':len(r.passed),'failed_ids':[t.id() for t,_ in r.errors+r.failures],'skipped_ids':[t.id() for t,_ in r.skipped],'python':platform.python_version(),'evidence_kinds':['SIMULATED_FAKEFS','LOCAL_TINY_PROCESS_FAULTS','BINARY_ADMISSION_REFUSAL'],'real_calibration':'NOT_RUN_HOST_APPROVAL_REQUIRED','cgroup_writes':0,'model_requests':0,'count_requests':0,'gcp_calls':0,'formal_ready':False,'formal_status':'BLOCKED_NOT_FROZEN','budget_within':None}
    write(out/'ACCEPTANCE.json',result);print(json.dumps(result,indent=2))
    if not r.wasSuccessful():print(log.getvalue()[-14000:])
    return 0 if r.wasSuccessful() and not r.skipped else 2
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();raise SystemExit(main(a.build,a.output))
