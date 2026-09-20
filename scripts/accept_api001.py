#!/usr/bin/env python3
"""Target gate: retained EXEC gate + API tests + real supervised mock-wire demo.

--review is deliberately a different status and cannot authorize LIVE calls.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from rcwg_api.common import Archive,canonical,sha
from rcwg_api.policy import source_snapshot,check_exec_sources,check_retained_test_sources,check_staged_snapshot

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--review',action='store_true');args=p.parse_args()
out=Path(args.output).absolute()
if not out.is_relative_to(ROOT/'runs'):raise SystemExit('output must be a new runs/ path')
store=Archive(out);before=source_snapshot();failures=[];commands=[];retained_source_count=None
if not args.review:
    if sys.version_info[:3]!=(3,12,14):failures.append('PYTHON_3_12_14_REQUIRED')
    try:
        check_exec_sources();retained_source_count=check_retained_test_sources();check_staged_snapshot(before)
    except Exception as error:failures.append(getattr(error,'code','BASELINE_CHECK_FAILED'))

def run(label,cmd,timeout=300):
    start=time.time_ns()
    try:
        result=subprocess.run(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
        code=result.returncode;raw=result.stdout
    except subprocess.TimeoutExpired as e:code=124;raw=e.stdout or b''
    store.put(label+'.log',raw)
    commands.append({'label':label,'argv':cmd,'exit_code':code,'elapsed_ns':time.time_ns()-start,'log_sha256':sha(raw)})
    if code!=0:failures.append(label)
    return code

if not failures:
    if not args.review:
        run('retained-exec-gate',[sys.executable,'scripts/accept_exec001.py','--output',str(out/'retained-exec')])
        if not failures:
            existing=json.loads((out/'retained-exec/ACCEPTANCE.json').read_text())
            required=json.loads((ROOT/'specs/api001/retained_test_ids.json').read_text())['required_methods']
            if not set(required).issubset(existing['tests']['passed_ids']):failures.append('RETAINED_708_IDS')
            win_base=json.loads((ROOT/'specs/api001/win01_retained_baseline.json').read_text())
            if not set(win_base['required_methods']).issubset(existing['tests']['passed_ids']):failures.append('RETAINED_821_IDS')
            for name,h in win_base['files_sha256'].items():
                if sha((ROOT/name).read_bytes())!=h:failures.append('WIN01_BASELINE_TEST_BYTES:'+name)
    run('api-tests',[sys.executable,'acceptance/api001/run_tests.py','--output',str(out/'api-unit')])
    cmd=[sys.executable,'-m','rcwg_api','demo','--output',str(out/'mock-wire-execution')]
    if args.review:cmd.append('--review-reference')
    if run('mock-wire-execution',cmd)==0:
        report=json.loads((out/'mock-wire-execution/observations/report.json').read_text())
        if report['actual_generate_dispatches']!=3 or report['actual_count_dispatches']!=3 or report['real_model_service_dispatches']!=0:
            failures.append('MOCK_WIRE_COUNTS')
        if any(not r.get('execution') or r['execution'].get('terminal_status')!='COMPLETED'
               or r['execution'].get('verification',{}).get('status')!='PASS' for r in report['generations']):
            failures.append('MOCK_REAL_EXECUTION_CHAIN')
        if not args.review and any(not r['execution'].get('execution_started') or not r['execution'].get('seal_sha256') for r in report['generations']):
            failures.append('SUPERVISED_EXECUTION_REQUIRED')
if source_snapshot()!=before:failures.append('SOURCE_CHANGED')
if not args.review:
    try:check_staged_snapshot(before)
    except Exception:failures.append('SOURCE_INDEX_MISMATCH_AT_END')
result={'status':('API001_REVIEW_OFFLINE_PASS' if args.review else 'API001_TARGET_OFFLINE_PASS') if not failures else 'API001_OFFLINE_BLOCKED',
        'python':sys.version.split()[0],'review_only':args.review,'commands':commands,'failures':failures,
        'source_sha256':before,'source_after_sha256':source_snapshot(),
        'windows_native_test_status':'SEPARATE_WINDOWS_ACCEPTANCE_REQUIRED','win01_retained_methods':821,
        'index_verified':not args.review and not failures,'retained_test_source_files':retained_source_count,'actual_live_model_requests':0,'formal_ready':False,
        'full_api001_accepted':False,'live_acceptance':'NOT_EXECUTED','invoice_cost_usd':None}
store.json('ACCEPTANCE.json',result)
print(json.dumps({k:result[k] for k in ('status','python','failures','actual_live_model_requests','formal_ready')},indent=2))
raise SystemExit(0 if not failures else 2)
