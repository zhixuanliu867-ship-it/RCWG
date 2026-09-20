"""Separate native Windows offline evidence. Never acquires credentials/network."""
import argparse,hashlib,importlib.util,io,json,os,pathlib,platform,sys,unittest
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def main():
    p=argparse.ArgumentParser();p.add_argument('--binding',required=True);p.add_argument('--output',required=True);p.add_argument('--snapshot',required=True);a=p.parse_args()
    if os.name!='nt':raise SystemExit('NATIVE_WINDOWS_REQUIRED')
    binding=json.loads(pathlib.Path(a.binding).read_text(encoding='utf-8'));snapshot=json.loads(pathlib.Path(a.snapshot).read_text(encoding='utf-8'))
    helper=pathlib.Path(binding['helper_path']);h=load('win01_native_helper',helper)
    testpath=pathlib.Path(__file__).with_name('windows_tests.py');tests=load('win01_native_tests',testpath);tests.h=h;tests.binding=binding
    class Result(unittest.TextTestResult):
        def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.passed=[]
        def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())
    output=pathlib.Path(a.output);output.mkdir(exist_ok=False)
    stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromModule(tests)
    r=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
    report={'status':'API001_WINDOWS_OFFLINE_PASS' if r.wasSuccessful() and r.testsRun==12 else 'API001_WINDOWS_OFFLINE_FAIL',
            'python':platform.python_version(),'pid':os.getpid(),'os':os.name,'windows_host':binding,'source_sha256':snapshot,
            'methods_run':r.testsRun,'passed_ids':r.passed,'failed_ids':[t.id() for t,_ in r.failures],'error_ids':[t.id() for t,_ in r.errors],
            'deployment_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (helper,testpath,pathlib.Path(__file__))},
            'actual_gcloud_invocations':0,'actual_cloud_requests':0,'actual_model_requests':0,'formal_ready':False}
    (output/'unittest.log').write_text(stream.getvalue(),encoding='utf-8');(output/'ACCEPTANCE.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','windows_host','passed_ids')},ensure_ascii=False))
    return 0 if report['status']=='API001_WINDOWS_OFFLINE_PASS' else 2
if __name__=='__main__':raise SystemExit(main())
