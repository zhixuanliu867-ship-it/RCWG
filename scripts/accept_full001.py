"""stdlib outer acceptance dispatcher; never installs dependencies or opens LIVE."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
TARGET='3.12.14'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['offline'],required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--python',type=Path);p.add_argument('--native-build',type=Path);p.add_argument('--resume',action='store_true')
    try:a=p.parse_args(argv)
    except SystemExit as exc:return 0 if exc.code==0 else 3
    sys.path.insert(0,str(ROOT))
    from rcwg_full.evidence import source_hashes,digest,safe_path
    out=safe_path(a.output)
    sources=source_hashes();lock=ROOT/'environments/full001/requirements.lock'
    interpreter=a.python or ROOT/'environments/full001/.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    identity={'revision':'FULL001_ACCEPTANCE_1','spec_hash':json.loads((ROOT/'docs/full001/SPEC_IDENTITY.json').read_text('utf-8'))['spec_hash'],
       'source_hash':digest(sources),'sources':sources,'requirements_lock_sha256':sha(lock),'target_python':TARGET,'interpreter':str(interpreter.absolute()),'mode':'offline'}
    try:
        if a.resume:
            if json.loads((out/'IDENTITY.json').read_text('utf-8'))!=identity:raise ValueError('ACCEPTANCE_RESUME_IDENTITY')
        else:out.mkdir(parents=True,exist_ok=False,mode=0o700);save(out/'IDENTITY.json',identity)
    except (OSError,ValueError) as exc:
        print(json.dumps({'phase':'INPUT','status':'INVALID','blockers':[str(exc)]}));return 3
    invocation=out/('invocation-'+str(time.time_ns()));invocation.mkdir(mode=0o700)
    stages=[];blockers=[]
    def run(name,command,expected_report=None):
        from rcwg_full.acceptance_stages import run_stage
        record=run_stage(out,name,command,source_hash=identity['source_hash'],cwd=ROOT,resume=a.resume,expected_report=expected_report)
        stages.append(record)
        if record.get('blocker'):blockers.append(name+':'+record['blocker'])
        return record['exit_code']
    actual={'interpreter_exists':interpreter.is_file(),'outer_python':platform.python_version(),'outer_executable':sys.executable}
    if interpreter.is_file():
        probe="import sys,platform,json,importlib.metadata as m;print(json.dumps({'python':platform.python_version(),'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'packages':{k:m.version(k) for k in ['pyarrow','pybind11']}}))"
        result=subprocess.run([str(interpreter),'-I','-c',probe],cwd=ROOT,capture_output=True,timeout=30)
        save(invocation/'environment-probe.json',{'command':[str(interpreter),'-I','-c',probe],'exit_code':result.returncode,'stdout':result.stdout.decode('utf8',errors='replace'),'stderr':result.stderr.decode('utf8',errors='replace')})
        if result.returncode:blockers.append('PREPARED_DEPENDENCIES_UNAVAILABLE')
        else:
            actual.update(json.loads(result.stdout))
            if actual['python']!=TARGET:blockers.append('TARGET_PYTHON_3_12_14_REQUIRED')
            if actual['prefix']==actual['base_prefix']:blockers.append('ISOLATED_INTERPRETER_REQUIRED')
            if actual['packages']!={'pyarrow':'21.0.0','pybind11':'3.0.1'}:blockers.append('LOCKED_DEPENDENCY_VERSIONS_REQUIRED')
    else:blockers.append('PREPARED_ISOLATED_INTERPRETER_MISSING')
    if os.name!='posix':blockers.append('LINUX_NATIVE_ACCEPTANCE_ENVIRONMENT_REQUIRED')
    print(json.dumps({'phase':'ENVIRONMENT','actual':actual,'lock_sha256':identity['requirements_lock_sha256'],'blockers':blockers},ensure_ascii=False))
    code=2 if blockers else 0
    if not blockers:
        py=str(interpreter.absolute());build=a.native_build or out/'native-build'/'build'
        native_code=0 if a.native_build else run('native-build',[py,'scripts/build_full001.py','--output',str(build.absolute())])
        if native_code==0:
            run('full001',[py,'acceptance/full001/run_tests.py','--native-build',str(build.absolute()),'--output',str((out/'full001/results').absolute())])
        run('inherited-python',[py,'acceptance/full001/run_tests.py','--suite-root','tests','--output',str((out/'inherited-python/results').absolute())])
        for name,builder,acceptor in [('native-original','scripts/build_native001.py','scripts/accept_native001.py'),
                                     ('n4-original','scripts/build_native001_n4.py','scripts/accept_native001_n4.py')]:
            original_build=out/(name+'-build')/'build'
            if run(name+'-build',[py,builder,'--output',str(original_build.absolute())])==0:
                run(name,[py,acceptor,'--build',str(original_build.absolute()),'--output',str((out/name/'results').absolute())])
        code=1 if any(r['status']=='FAIL' for r in stages) else 2 if any(r['status']=='BLOCKED' for r in stages) else 0
    if source_hashes()!=sources:code=1;blockers.append('SOURCE_CHANGED_DURING_ACCEPTANCE')
    # Derive requirement evidence from this exact run. Progress-file PASS labels
    # are never accepted as coverage. Delivery failures preserve all test runs.
    pending=[];software_evidence=None;delivery=None
    if code==0:
        try:
            from rcwg_full.acceptance_evidence import build_evidence
            from rcwg_full.acceptance_delivery import source_delivery
            software_evidence=build_evidence(out/'full001/results',build)
            save(invocation/'SOFTWARE_EVIDENCE.json',software_evidence)
            delivery=source_delivery(invocation/'delivery')
            for row in software_evidence['requirements']:
                if row['requirement_id'].startswith('M00-'):
                    row['status']='PASS';row['actual_evidence'].append({'clean_application':delivery})
            save(invocation/'REQUIREMENT_TO_EVIDENCE.json',software_evidence['requirements'])
        except (ValueError,KeyError,OSError) as exc:
            code=1;blockers.append('SOFTWARE_EVIDENCE_OR_DELIVERY:'+str(exc))
    if software_evidence:
        pending=[r['requirement_id'] for r in software_evidence['requirements'] if not r['requirement_id'].startswith('EXT-') and r['status']!='PASS']
    else:pending=[r['requirement_id'] for r in json.loads((ROOT/'specs/full001/requirements.json').read_text('utf8'))['requirements'] if not r['requirement_id'].startswith('EXT-')]
    report={'phase':'SOFTWARE_TOTAL_ACCEPTANCE','status':'PASS' if code==0 else 'BLOCKED' if code==2 else 'FAIL',
       'exit_code':code,'blockers':blockers,'pending_software_requirements':pending,'environment':actual,
       'identity':identity,'stages':stages,'software_accepted':code==0,'formal_ready':False,'source_delivery':delivery,
       'external_states':{'HOST_CALIBRATED':False,'DATA_FROZEN':False,'SERVICE_READY':False,'FORMAL_READY':False}}
    save(invocation/'ACCEPTANCE.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in {'identity','stages'}},ensure_ascii=False));return code


if __name__=='__main__':raise SystemExit(main())
