#!/usr/bin/env python3
"""Complete EXEC F1 offline gate. External CI/delivery proof is joined separately."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rcwg_spec.common import canonical,digest
from rcwg_exec.context import source_closure
from rcwg_exec.acceptance_cases import development_cases
from rcwg_exec.campaign import run_campaign
from rcwg_exec.coverage import runtime_coverage


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def source_hashes():
    paths={ROOT/n.decode() for n in git('ls-files','-z').split(b'\0') if n}
    # Include untracked runtime, tests and acceptance sources so omission fails.
    for folder in ('rcwg_boot','rcwg_spec','rcwg_exec','tests','scripts','specs','prompts','acceptance'):
        paths.update(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
def index_mismatches(hashes):
    index={}
    for entry in git('ls-files','--stage','-z').split(b'\0'):
        if entry:
            meta,name=entry.split(b'\t',1);mode,oid,stage=meta.split()
            if stage==b'0':index[name.decode()]=oid.decode()
    bad=[]
    for name in hashes:
        data=(ROOT/name).read_bytes();oid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if index.get(name)!=oid:bad.append(name)
    return bad


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(ROOT/'runs'):raise SystemExit('Private output must be inside this checkout runs/')
    out.mkdir(parents=True,exist_ok=False)
    report={'ticket':'RCWG-EXEC-001','status':'EXEC001_IN_PROGRESS','full_exec001_accepted':False,
        'environment':'GITHUB_CI' if os.environ.get('GITHUB_ACTIONS')=='true' else 'OWNER_WSL' if 'microsoft' in platform.release().lower() else 'OTHER_LINUX',
        'python':platform.python_version(),'platform':platform.platform(),'kernel':platform.release(),
        'commands':[],'gates':{},'failures':[],'formal_ready':False,'real_model_requests':0,'cloud_mutations':0,
        'started_unix_ns':time.time_ns(),'commit_at_start':git('rev-parse','HEAD').decode().strip()}
    bad=report['failures'];before=source_hashes();index_bad=index_mismatches(before)
    report['source_before_sha256']=before;report['source_index_mismatches_before']=index_bad
    if index_bad:bad.append('UNSTAGED_SOURCE_BYTES')
    if platform.python_version()!='3.12.14' or sys.platform!='linux':bad.append('REQUIRED_LINUX_PYTHON_3_12_14')
    baseline=json.loads((ROOT/'specs/exec001/baseline_merges.json').read_bytes())
    ancestry=[]
    for row in baseline['steps']:
        reviewed=row['head'];merge=row['merge']['sha']
        ok=all(subprocess.run(['git','merge-base','--is-ancestor',sha,'HEAD'],cwd=ROOT).returncode==0 for sha in (reviewed,merge))
        tree=git('rev-parse',merge+'^{tree}').decode().strip()
        ancestry.append({'pr':row['pr'],'reviewed_head':reviewed,'merge':merge,'merged_tree':tree,'ancestor':ok})
        if not ok or tree!=row['merged_tree']:bad.append('BASELINE_ANCESTRY')
    report['baseline_ancestry']=ancestry;report['gates']['X00']='PASS' if all(x['ancestor'] for x in ancestry) else 'FAIL'
    frozen=json.loads((ROOT/'specs/exec001/baseline_test_sha256.json').read_bytes())['files']
    frozen.update(json.loads((ROOT/'specs/exec001/reference_test_sha256.json').read_bytes())['files'])
    changed=[name for name,h in frozen.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h]
    report['protected_test_bytes']={'files':len(frozen),'changed':changed}
    if changed:bad.append('ORIGINAL_585_PLUS_77_CHANGED')
    for label,argv,expected in [
        ('original-spec001b',['scripts/accept_spec001b.py','--output',str(out/'original-spec001b'),'--require-python','3.12.14'],0),
        ('reference-core',['scripts/accept_exec001_reference.py','--output',str(out/'reference-core')],0)]:
        cmd=[sys.executable,*argv];r=subprocess.run(cmd,cwd=ROOT,capture_output=True)
        (out/(label+'.stdout.log')).write_bytes(r.stdout);(out/(label+'.stderr.log')).write_bytes(r.stderr)
        report['commands'].append({'command':cmd,'exit_code':r.returncode,'expected_exit_code':expected,'stdout':label+'.stdout.log','stderr':label+'.stderr.log'})
        if r.returncode!=expected:bad.append(label+'_FAILED')
    b=json.loads((out/'original-spec001b/ACCEPTANCE.json').read_bytes());ref=json.loads((out/'reference-core/ACCEPTANCE.json').read_bytes())
    report['tests']=b['tests'];passed=b['tests']['passed_ids']
    required=json.loads((ROOT/'specs/exec001/required_full_test_ids.json').read_bytes())['required_test_ids']
    missing=sorted(set(required)-set(passed));report['missing_required_test_ids']=missing
    if missing or len(required)!=len(set(required)):bad.append('MISSING_REQUIRED_TEST_IDS')
    cases,expected=development_cases(out/'development-inputs')
    # Expected outcome labels are frozen before actual campaign execution too.
    (out/'expected_outcomes.json').write_bytes(canonical(expected))
    report['commands'].append({'command':['python-api','development_cases','run_campaign'],
                              'inputs':'development-inputs','expected':'expected_outcomes.json','output':'actual-campaign'})
    campaign=run_campaign(cases,output=out/'actual-campaign');report['campaign']=campaign
    actual={r['attempt_id']:{k:r[k] for k in ('outcome','verification')} for r in campaign['outcomes']}
    mismatches=[{'case':name,'expected':want,'actual':actual.get(name)} for name,want in expected.items() if actual.get(name)!=want]
    report['commands'][-1]['exit_code']=1 if mismatches else 0
    report['commands'][-1]['expected_exit_code']=0
    report['case_mismatches']=mismatches
    if mismatches:bad.append('ACTUAL_CASE_OUTCOME_MISMATCH')
    matrix=runtime_coverage(out/'actual-campaign',passed)
    (out/'runtime-coverage.json').write_bytes(canonical(matrix))
    report['runtime_coverage']={k:matrix[k] for k in ('status','operator_count','reference_branch_count','violations')}
    if matrix['status']!='EXEC001_RUNTIME_COVERAGE_PASS':bad.append('RUNTIME_COVERAGE')
    for gate,data in matrix['gate_test_coverage'].items():report['gates'][gate]=data['status']
    if mismatches:
        for gate in ('X01','X02','X03','X04','X05','X06','X08','X09','X10','X12'):report['gates'][gate]='FAIL'
    report['original_spec001b_status']=b['status'];report['reference_core_status']=ref['status']
    report['original_negative_review']=b.get('negative_review')
    report['gates']['X13']='PASS' if (b['status']=='SPEC001B_OFFLINE_GATES_PASS' and ref['status']=='EXEC001_REFERENCE_CORE_PASS'
        and not changed and not missing and not b['tests']['skipped_ids'] and not b['tests']['expected_failure_ids']) else 'FAIL'
    after=source_hashes();index_after=index_mismatches(after)
    report['source_after_sha256']=after;report['source_index_mismatches_after']=index_after
    report['runtime_closure_sha256']=source_closure();report['runtime_closure_hash']=digest(source_closure())
    report['staged_tree']=git('write-tree').decode().strip()
    if before!=after or index_after:bad.append('SOURCE_CHANGED_DURING_ACCEPTANCE');report['gates']['X14']='FAIL'
    report['gates']['X15']='EXTERNAL_DELIVERY_PROOF_REQUIRED'
    report['external_requirements']=['independent GitHub CI for exact submitted commit','clean final patch apply tree proof','delivery evidence and SHA256']
    if any(v=='FAIL' for v in report['gates'].values()):bad.append('GATE_FAILED')
    report['status']='EXEC001_OFFLINE_GATES_PASS' if not bad else 'EXEC001_OFFLINE_GATES_FAILED'
    report['finished_unix_ns']=time.time_ns()
    report['evidence_files_sha256']={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()}
    (out/'ACCEPTANCE.json').write_bytes(canonical(report))
    print(json.dumps({k:report[k] for k in ('status','environment','python','staged_tree','runtime_coverage','gates','failures','formal_ready')},indent=2))
    return 0 if not bad else 1

if __name__=='__main__':raise SystemExit(main())
