#!/usr/bin/env python3
"""Offline reference-core acceptance; full EXEC-001 is a separate Codex gate."""
from __future__ import annotations
import argparse,contextlib,hashlib,importlib.util,json,platform,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('spec_gate',ROOT/'scripts/accept_spec001b.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def source_hashes():
    files=[]
    for folder in ('rcwg_boot','rcwg_spec','rcwg_exec','tests','scripts','acceptance','specs/exec001'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}

def index_match(hashes):
    errors=[]
    for name,h in hashes.items():
        r=subprocess.run(['git','show',':'+name],cwd=ROOT,capture_output=True)
        if r.returncode or hashlib.sha256(r.stdout).hexdigest()!=h:errors.append(name)
    return errors

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--review-environment',action='store_true')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'ticket':'RCWG-EXEC-001','checkpoint':'REFERENCE_CORE','python':platform.python_version(),
            'target_python':'3.12.14','target_environment_pass':platform.python_version()=='3.12.14',
            'formal_ready':False,'full_exec001_accepted':False,'failures':[],'commands':[]}
    bad=report['failures'];before=source_hashes();mismatch=index_match(before)
    frozen=json.loads((ROOT/'specs/exec001/baseline_test_sha256.json').read_text())['files']
    changed_baseline=[name for name,h in frozen.items()
                      if not (ROOT/name).is_file() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h]
    report['baseline_test_files_verified']=len(frozen)
    report['changed_baseline_test_files']=changed_baseline
    if changed_baseline:bad.append('REVIEWED_BASELINE_TEST_BYTES_CHANGED')
    if mismatch:bad.append('UNSTAGED_SOURCE_BYTES')
    if not a.review_environment and not report['target_environment_pass']:bad.append('TARGET_PYTHON_MISMATCH')
    with (out/'unittest.txt').open('x') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        suite=unittest.TestLoader().discover(str(ROOT/'tests'))
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=base.EvidenceResult).run(suite)
    report['tests']={'methods':result.testsRun,'passed_ids':result.passed_ids,'failed_ids':sorted(result.failed_ids),
                     'skipped_ids':result.skipped_ids,'subcases':result.subcase_count,
                     'expected_failure_ids':[t.id() for t,_ in result.expectedFailures]}
    required=json.loads((ROOT/'specs/exec001/required_reference_test_ids.json').read_text())['required_test_ids']
    missing=sorted(set(required)-set(result.passed_ids));report['missing_required_ids']=missing
    if not result.wasSuccessful() or missing or result.skipped_ids or result.expectedFailures:bad.append('TESTS_OR_REQUIRED_COVERAGE')
    checks=[('boot',['-m','rcwg_boot','check'],0),('formal',['-m','rcwg_boot','check','--formal'],2),
            ('sentinels',['acceptance/spec001b/run_compiler_sentinels.py'],0),
            ('reference-demo',['-m','rcwg_exec','demo','--output',str(out/'actual-demo')],0),
            ('public-guard',['scripts/check_public_tree.py'],0)]
    for name,cmd,expected in checks:
        r=subprocess.run([sys.executable,*cmd],cwd=ROOT,capture_output=True,text=True)
        (out/(name+'.stdout.txt')).write_text(r.stdout);(out/(name+'.stderr.txt')).write_text(r.stderr)
        report['commands'].append({'command':[sys.executable,*cmd],'exit_code':r.returncode,'expected_exit_code':expected})
        if r.returncode!=expected:bad.append(name+'_FAILED')
    after=source_hashes()
    if before!=after or index_match(after):bad.append('SOURCE_CHANGED_DURING_TEST')
    report['source_sha256']=after;report['staged_tree']=subprocess.check_output(['git','write-tree'],cwd=ROOT,text=True).strip()
    report['tracked_files_match_index']=not mismatch;report['mismatched_files']=mismatch
    report['status']='EXEC001_REFERENCE_CORE_PASS' if not bad else 'EXEC001_REFERENCE_CORE_FAILED'
    report['evidence_file_sha256']={str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(out.rglob('*')) if f.is_file()}
    (out/'ACCEPTANCE.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','checkpoint','python','target_environment_pass','full_exec001_accepted','formal_ready','failures')},indent=2))
    return 0 if not bad else 1
if __name__=='__main__':raise SystemExit(main())
