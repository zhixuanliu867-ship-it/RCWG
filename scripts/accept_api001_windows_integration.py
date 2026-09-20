"""WSL supervisor + actual Windows fake-wire integration, never a LIVE sample."""
import argparse,base64,json,subprocess,sys,time
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rcwg_api.common import Archive,canonical,digest,read,sha,fail
from rcwg_api.policy import source_snapshot,default_config,windows_config
from rcwg_api.windows_bridge import envelope,decode_result,wsl_path,validate_host
from rcwg_api.pilot import make_manifest,run_pilot
from rcwg_api.vertex import Response
from rcwg_api.mock import wire_fixtures
from rcwg_exec.demo import prepare_fixture
class WindowsFixtureTransport:
    mode='MOCK'
    def __init__(self,binding,responses,manifest_hash):
        self.config=windows_config(binding);self.responses=list(responses);self.manifest_hash=manifest_hash
        self.dispatch_count=0;self.receipts=[]
    def send(self,kind,body,request_id):
        fixture=self.responses.pop(0)
        reservation={'request_id':request_id,'kind':kind,'amount_microusd':self.config['reservation_microusd'][kind],
                     'reserved_before_io':True,'manifest_sha256':self.manifest_hash,'mode':'LIVE'}
        e=envelope(self.config,self.manifest_hash,request_id,kind,body,reservation)
        driver=Path(self.config['windows_host']['helper_path'].replace('\\','/')).with_name('api001_fake_wire.py').as_posix()
        source=ROOT/'acceptance/api001/api001_fake_wire.py'
        if sha(wsl_path(driver).read_bytes())!=sha(source.read_bytes()):fail('OFFLINE_DRIVER_SOURCE_CHANGED')
        incoming={'envelope':e,'fake_response':{'status':fixture.status,'body_b64':base64.b64encode(fixture.body).decode()}}
        start=time.perf_counter_ns()
        proc=subprocess.run([str(wsl_path(self.config['windows_host']['python_executable'])),'-I','-B',driver],input=canonical(incoming),capture_output=True,timeout=30)
        if proc.returncode:fail('WINDOWS_OFFLINE_DRIVER_FAILED')
        events=[json.loads(line) for line in proc.stdout.splitlines()]
        if events[-1].pop('synthetic_fixture',None) is not True:fail('OFFLINE_DRIVER_LABEL_REQUIRED')
        result=decode_result(b'\n'.join(canonical(x) for x in events),e)
        result.update(offline_fixture=True,wsl_bridge_elapsed_ns=time.perf_counter_ns()-start)
        self.receipts.append(result);self.dispatch_count+=1
        return Response(result['http_status'],base64.b64decode(result['response_b64']),result['headers'],result['http_elapsed_ns'])
def main():
    p=argparse.ArgumentParser();p.add_argument('--binding',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    binding=read(Path(a.binding));validate_host(binding,files=True);store=Archive(Path(a.output));before=source_snapshot();results=[]
    for name in ('correct','wrong'):
        case=Archive(store.path/name);task,plans,recipe,data=prepare_fixture(case.path/'fixture')
        plan=deepcopy(plans['streaming_heap' if name=='correct' else 'omitted_filter'])
        manifest=make_manifest(task,default_config('rcwg-mock-pilot'),before,recipe_sha256=digest(recipe))
        transport=WindowsFixtureTransport(binding,wire_fixtures(plan),digest(manifest))
        outcome=run_pilot(task,recipe,data,manifest,output=case.path/'observations',transport=transport)
        case.json('windows_fake_receipts.json',transport.receipts)
        report=outcome['report'];executions=[r.get('execution') for r in report['generations']]
        results.append({'case':name,'plan_sha256':digest(plan),'dispatches':transport.dispatch_count,'real_model_requests':0,
                        'execution_outcomes':executions,'seal_sha256':outcome['seal_sha256'],'reread':outcome['reread']})
    errors=[]
    for case in results:
        wanted='PASS' if case['case']=='correct' else 'FAIL'
        if case['dispatches']!=6 or any(not e or e.get('execution_started') is not True or e.get('terminal_status')!='COMPLETED' or e.get('verification',{}).get('status')!=wanted for e in case['execution_outcomes']):errors.append(case['case'])
    if source_snapshot()!=before:errors.append('SOURCE_CHANGED')
    report={'status':'API001_WINDOWS_WSL_INTEGRATION_PASS' if not errors else 'API001_WINDOWS_WSL_INTEGRATION_FAIL',
            'cases':results,'errors':errors,'source_sha256':before,'windows_host':binding,'python':sys.version.split()[0],
            'actual_windows_subprocesses':sum(r['dispatches'] for r in results),'actual_gcloud_invocations':0,'actual_model_requests':0,'formal_ready':False}
    store.json('ACCEPTANCE.json',report);print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','windows_host','cases')},indent=2))
    return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
