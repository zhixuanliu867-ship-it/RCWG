"""Record every actual test outcome and source identity; no count-based acceptance."""
from pathlib import Path
import argparse
import json
import platform
import sys
import time
import unittest
import os
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from rcwg_full.evidence import exclusive_directory,write,source_hashes


class Result(unittest.TextTestResult):
    def __init__(self,*a,**k):super().__init__(*a,**k);self.outcomes=[];self.subtests=[]
    def addSuccess(self,test):super().addSuccess(test);self.outcomes.append({'test_id':test.id(),'status':'PASS'})
    def addFailure(self,test,err):super().addFailure(test,err);self.outcomes.append({'test_id':test.id(),'status':'FAIL'})
    def addError(self,test,err):super().addError(test,err);self.outcomes.append({'test_id':test.id(),'status':'ERROR'})
    def addSkip(self,test,reason):super().addSkip(test,reason);self.outcomes.append({'test_id':test.id(),'status':'SKIP','reason':reason})
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        status='PASS' if err is None else 'FAIL' if issubclass(err[0],test.failureException) else 'ERROR'
        self.subtests.append({'parent_test_id':test.id(),'subtest_id':subtest.id(),'status':status})
        if err is not None and not any(row['test_id']==test.id() for row in self.outcomes):self.outcomes.append({'test_id':test.id(),'status':status})


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--pattern',action='append')
    p.add_argument('--native-build',type=Path)
    p.add_argument('--suite-root',type=Path,default=Path(__file__).parent)
    a=p.parse_args()
    if a.native_build:os.environ['RCWG_FULL_BUILD']=str(a.native_build.absolute())
    out=exclusive_directory(a.output);os.environ['RCWG_FULL_TEST_EVIDENCE']=str((out/'evidence').absolute());sources=source_hashes()
    from rcwg_full.acceptance_identity import git_identity,dependencies,file_manifest,file_hash
    checkout=git_identity();installed=dependencies()
    build_identity=None if not a.native_build else {'manifest_sha256':file_hash(a.native_build/'BUILD.json'),'manifest':json.loads((a.native_build/'BUILD.json').read_text('utf8'))}
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(a.suite_root),pattern=pattern) for pattern in (a.pattern or ['test_*.py']))
    def flatten(s):
        for test in s:
            if isinstance(test,unittest.TestSuite):yield from flatten(test)
            else:yield test.id()
    expected=list(flatten(suite))
    if len(expected)!=len(set(expected)):raise RuntimeError('DUPLICATE_TEST_ID')
    write(out/'EXPECTED_TESTS.json',{'test_ids':expected,'source':sources,'frozen_before_execution':True})
    with (out/'unittest.log').open('x',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
    passed=result.wasSuccessful() and not result.skipped and len(result.outcomes)==result.testsRun and set(expected)=={t['test_id'] for t in result.outcomes} and sources==source_hashes() and checkout==git_identity()
    report={'scope':'TESTS_EXECUTED_ONLY_NOT_FULL001_ACCEPTANCE','status':'PASS' if passed else 'FAIL',
        'python':platform.python_version(),'platform':platform.platform(),'executable':sys.executable,
        'command':sys.argv,'exit_code':0 if passed else 1,'git_identity':checkout,'dependencies':installed,'native_build':build_identity,'artifact_files':file_manifest(out),'source':sources,'tests':result.outcomes,'subtests':result.subtests,'tests_run':result.testsRun,
        'formal_ready':False,'implementation_complete':False}
    write(out/'TEST_RESULTS.json',report);print(json.dumps({k:v for k,v in report.items() if k not in {'source','tests','artifact_files','native_build','subtests'}}));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
