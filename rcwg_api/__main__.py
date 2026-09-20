"""Offline by default. `live` requires exact target validation and local approval."""
from pathlib import Path
import argparse
import json
import sys
from .common import ROOT,ApiError,fail,read,canonical,sha,digest,private_path
from .policy import default_config,source_snapshot
from .pilot import prepare,make_manifest,run_pilot,audit
from .mock import MockTransport,wire_fixtures
from .vertex import GcloudToken,VertexTransport

def _private_output(path):
    p=private_path(Path(path))
    if not p.is_relative_to((ROOT/'runs').absolute()):fail('OUTPUT_MUST_BE_IN_RUNS')
    return p

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('prepare');p.add_argument('--project',required=True);p.add_argument('--service-account',required=True)
    p.add_argument('--output',required=True);p.add_argument('--allow-environment-proxy',action='store_true')
    p=sub.add_parser('demo');p.add_argument('--output',required=True);p.add_argument('--review-reference',action='store_true')
    p=sub.add_parser('live');p.add_argument('--prepared',required=True);p.add_argument('--approval',required=True)
    p.add_argument('--offline-acceptance',required=True);p.add_argument('--ack-paid-model-requests',action='store_true')
    p=sub.add_parser('audit');p.add_argument('--output',required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--seal-sha256',required=True)
    args=parser.parse_args()
    try:
        if args.cmd=='prepare':
            cfg=default_config(args.project);cfg['service_account']=args.service_account;cfg['allow_environment_proxy']=args.allow_environment_proxy
            result=prepare(_private_output(args.output),cfg)
        elif args.cmd=='demo':
            from rcwg_exec.demo import prepare_fixture
            from .common import Archive
            root=Archive(_private_output(args.output)).path
            task,plans,recipe,data=prepare_fixture(root/'fixture')
            manifest=make_manifest(task,default_config('rcwg-mock-pilot'),source_snapshot(),recipe_sha256=digest(recipe))
            executor=None
            if args.review_reference:
                from rcwg_exec.datasets import FileRegistry
                from rcwg_exec.runner import run_f1_reference
                def executor(task,plan,recipe,data,output,generation_id):
                    registry=FileRegistry(task,{recipe['source_id']:Path(data)},allowed_root=Path(data).parent)
                    return run_f1_reference(task,plan,registry=registry,recipe=recipe,output=output,
                                            record_id=generation_id,generation_id=generation_id,repeat_id='r0')
            complete=run_pilot(task,recipe,data,manifest,output=root/'observations',transport=MockTransport(wire_fixtures(plans['streaming_heap'])),executor=executor)
            result={'status':complete['report']['status'],'generation_outcomes':[{k:r[k] for k in ('generation_id','status')} for r in complete['report']['generations']],
                    'real_model_requests':0,'review_reference_only':args.review_reference,'seal_sha256':complete['seal_sha256'],
                    'manifest_sha256':digest(manifest),'formal_ready':False}
        elif args.cmd=='live':
            if not args.ack_paid_model_requests:fail('PAID_ACK_REQUIRED')
            root=_private_output(args.prepared);manifest=read(root/'expected_generations.json')
            task=read(root/'fixture/task.json');recipe=read(root/'fixture/verification_recipe.json')
            approval=read(_private_output(args.approval));config=manifest['config']
            result0=run_pilot(task,recipe,root/'fixture/records.jsonl',manifest,output=root/'observations',mode='LIVE',
                       transport=VertexTransport(config,GcloudToken(config)),approval=approval,offline_acceptance=_private_output(args.offline_acceptance))
            r=result0['report'];result={'status':r['status'],'real_model_service_dispatches':r['real_model_service_dispatches'],
                    'stop_reason':r['stop_reason'],'seal_sha256':result0['seal_sha256'],
                    'live_acceptance':'INDEPENDENT_REVIEW_REQUIRED','formal_ready':False}
        else:result=audit(_private_output(args.output),args.manifest_sha256,args.seal_sha256)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result.get('stop_reason') else 0
    except Exception as e:
        # CLI diagnostics never print exception text or credential output.
        result={'status':'API001_BLOCKED','code':e.code if isinstance(e,ApiError) else 'LOCAL_'+type(e).__name__,
                'formal_ready':False,'live_acceptance':'NOT_ESTABLISHED'}
        print(json.dumps(result,ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
