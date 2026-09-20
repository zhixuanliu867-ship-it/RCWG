"""Complete N0–N3 offline/native gate. N4 calibration is explicitly blocked."""
from pathlib import Path
import argparse
import io
import json
import platform
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_native.evidence import ROOT,bootstrap,read,write,sha,canonical,closure_hashes,reread
from rcwg_native.supervisor import binary_binding
from rcwg_api.policy import source_snapshot,check_staged_snapshot,check_exec_sources,check_retained_test_sources

class Result(unittest.TextTestResult):
    def __init__(self,*a,**kw):super().__init__(*a,**kw);self.passed=[]
    def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())

def flatten(suite):
    for t in suite:
        if isinstance(t,unittest.TestSuite):yield from flatten(t)
        else:yield t

def main(build,output):
    out=bootstrap(output);failures=[];before=source_snapshot();check_staged_snapshot(before)
    if platform.system()!='Linux' or platform.python_version()!='3.12.14':raise RuntimeError('TARGET_LINUX_PYTHON_3_12_14_REQUIRED')
    binary,manifest=binary_binding(build,'diagnostic');binary_binding(build,'performance')
    write(out/'SOURCE_AND_BINARY_MANIFEST.json',manifest)
    check_exec_sources();retained=check_retained_test_sources()
    sys.path.insert(0,str(ROOT/'native001_tests'))
    import test_native,test_values,test_supervisor
    modules=[test_native,test_values,test_supervisor]
    for m in modules:m.BUILD=Path(build).absolute();m.OUTPUT=out;m.EVIDENCE.clear()
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in modules)
    ids=sorted(t.id() for t in flatten(suite));frozen=read(ROOT/'specs/native001/frozen_test_ids.json')
    if ids!=frozen['test_ids']:raise RuntimeError('FROZEN_TEST_DENOMINATOR_MISMATCH')
    for name,digest in frozen['test_sources'].items():
        if sha((ROOT/name).read_bytes())!=digest:raise RuntimeError('FROZEN_TEST_SOURCE_MISMATCH')
    write(out/'EXPECTED_TESTS.json',{'test_ids':ids,'source_sha256':frozen['test_sources'],'manifest_sha256':sha((ROOT/'specs/native001/frozen_test_ids.json').read_bytes()),'frozen_before_tests':True})
    log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
    write(out/'unittest.log',log.getvalue().encode());write(out/'PASSED_TEST_IDS.json',result.passed)
    records=[row for m in modules for row in m.EVIDENCE]
    write(out/'ACTUAL_RUNS.json',records)
    if not result.wasSuccessful() or result.skipped:failures.append('TEST_FAILURE_OR_SKIP')
    if result.testsRun!=len(ids):failures.append('EXPECTED_TESTS_MISSING')
    branches={}
    for record in records:
        r=record['result']
        if r['terminal_status']!='COMPLETED' or r['verification']['status']!='PASS':continue
        folder=out/record['run_directory']
        try:reread(folder,r['seal_sha256'])
        except (ValueError,KeyError,OSError):failures.append('RUN_SEAL_INVALID');continue
        for d in r.get('actual_dispatch',[]):
            key=d['operator']+':'+d['implementation']
            branches.setdefault(key,[]).append({'test_id':record['test_id'],'run_directory':record['run_directory'],'run_id':r['run_id'],'expected_manifest_sha256':r['expected_manifest_sha256'],'seal_sha256':r['seal_sha256'],'sequence':d['sequence'],'scope':record.get('scope','WORKIR_STATIC_ADMISSION_AND_NATIVE_EXECUTION')})
    expected=['scan:sequential','filter:scalar','filter:vectorized','top_k:full_sort','top_k:streaming_heap','project:column_view','project:copy','emit:json_artifact']
    if set(branches)!=set(expected):failures.append('ACTUAL_BRANCH_COVERAGE_MISSING')
    if source_snapshot()!=before:failures.append('SOURCE_CHANGED_DURING_TESTS')
    check_staged_snapshot(source_snapshot())
    coverage={'revision':'NATIVE001_ACTUAL_COVERAGE_V1','branches':[{'branch':b,'status':'PASS' if branches.get(b) else 'FAIL','actual_runs':branches.get(b,[])} for b in expected],
              'typed_wire_cases_separate':True,'native_test_ids':[x for x in ids if x.startswith(('test_native.','test_values.'))],
              'mock_test_ids':[x for x in ids if x.startswith('test_supervisor.CgroupMockTests.')],
              'local_process_fault_test_ids':[x for x in ids if x.startswith('test_supervisor.ProcessLifecycleTests.')],
              'target_host_calibration':'BLOCKED_RUNTIME_HOST_APPROVAL','budget_within':None,'formal_ready':False}
    write(out/'ACTUAL_COVERAGE_MATRIX.json',coverage)
    acceptance={'status':'NATIVE001_N0_N3_OFFLINE_NATIVE_PASS' if not failures else 'NATIVE001_FAILED','python':platform.python_version(),'system':platform.platform(),
                'tests_run':result.testsRun,'tests_expected':len(ids),'passed':len(result.passed),'failures':failures,
                'failed_ids':[t.id() for t,_ in result.failures+result.errors],'skipped_ids':[t.id() for t,_ in result.skipped],
                'native_runs':len(test_native.EVIDENCE)+len(test_values.EVIDENCE),'actual_branches':len(branches),
                'N1':'PASS' if not failures else 'FAIL','N2':'PASS' if not failures else 'FAIL','N3_interface':'PASS' if not failures else 'FAIL',
                'N06_real_isolation':'BLOCKED_RUNTIME_HOST_APPROVAL','N07_calibration':'NOT_RUN_REQUIRES_N4_APPROVAL',
                'retained_source_files':retained,'retained_regression_execution':'SEPARATE_EXEC_API_CLOUD_ACCEPTANCE_LOGS_REQUIRED',
                'windows_acceptance':'SEPARATE_WINDOWS_LOG_REQUIRED','build_environment':manifest['platform'],'binary_source_verified':True,
                'model_requests':0,'count_requests':0,'cloud_builds':0,'cloud_jobs':0,'cloud_workflows':0,'iam_changes':0,'system_installs':0,'cgroup_writes':0,
                'budget_within':None,'formal_ready':False,'formal_status':'BLOCKED_NOT_FROZEN'}
    write(out/'ACCEPTANCE.json',acceptance);print(json.dumps(acceptance,indent=2));
    if failures:print(log.getvalue()[-16000:])
    return 0 if not failures else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();raise SystemExit(main(a.build,a.output))
