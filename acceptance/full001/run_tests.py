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
    def __init__(self,*a,**k):super().__init__(*a,**k);self.outcomes=[]
    def addSuccess(self,test):super().addSuccess(test);self.outcomes.append({'test_id':test.id(),'status':'PASS'})
    def addFailure(self,test,err):super().addFailure(test,err);self.outcomes.append({'test_id':test.id(),'status':'FAIL'})
    def addError(self,test,err):super().addError(test,err);self.outcomes.append({'test_id':test.id(),'status':'ERROR'})
    def addSkip(self,test,reason):super().addSkip(test,reason);self.outcomes.append({'test_id':test.id(),'status':'SKIP','reason':reason})


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--pattern',default='test_*.py')
    p.add_argument('--native-build',type=Path)
    a=p.parse_args()
    if a.native_build:os.environ['RCWG_FULL_BUILD']=str(a.native_build.absolute())
    out=exclusive_directory(a.output);sources=source_hashes()
    suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern=a.pattern)
    with (out/'unittest.log').open('x',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
    passed=result.wasSuccessful() and not result.skipped and len(result.outcomes)==result.testsRun and sources==source_hashes()
    report={'scope':'TESTS_EXECUTED_ONLY_NOT_FULL001_ACCEPTANCE','status':'PASS' if passed else 'FAIL',
        'python':platform.python_version(),'platform':platform.platform(),'executable':sys.executable,
        'command':sys.argv,'source':sources,'tests':result.outcomes,'tests_run':result.testsRun,
        'formal_ready':False,'implementation_complete':False}
    write(out/'TEST_RESULTS.json',report);print(json.dumps({k:v for k,v in report.items() if k not in {'source','tests'}}));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
