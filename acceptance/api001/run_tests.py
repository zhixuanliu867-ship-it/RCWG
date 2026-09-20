"""Machine-readable offline API tests with a fixed required-method manifest."""
import argparse,io,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.passed=[]
    def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())
log=io.StringIO();suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_api001*.py')
r=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
required=json.loads((ROOT/'specs/api001/required_api_test_ids.json').read_text())['required_methods']
missing=sorted(set(required)-set(r.passed))
report={'methods_run':r.testsRun,'passed_ids':sorted(r.passed),'missing_required_ids':missing,
        'failed_ids':[t.id() for t,_ in r.failures],'error_ids':[t.id() for t,_ in r.errors],
        'skipped':[t.id() for t,_ in r.skipped],'expected_failures':[t.id() for t,_ in r.expectedFailures],
        'unexpected_successes':[t.id() for t in r.unexpectedSuccesses],
        'actual_live_model_requests':0,'all_HTTP_responses':'SYNTHETIC_TEST_FIXTURES','formal_ready':False}
passed=r.wasSuccessful() and not missing and not r.skipped and not r.expectedFailures
report['status']='API001_UNIT_PASS' if passed else 'API001_UNIT_FAIL'
from rcwg_api.common import Archive
store=Archive(Path(a.output));store.put('unittest.log',log.getvalue().encode());store.json('RESULT.json',report)
print(log.getvalue());print(json.dumps({k:v for k,v in report.items() if k!='passed_ids'},indent=2))
raise SystemExit(0 if passed else 2)
