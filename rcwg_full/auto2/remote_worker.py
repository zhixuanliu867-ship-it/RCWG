"""Run a public-only job on the isolated VM; gold remains in a different identity."""
import argparse,json,os
from pathlib import Path
from types import SimpleNamespace
from rcwg_full.evidence import read,write,digest,source_hashes,sha
from rcwg_full.runtime.supervisor import execute
from rcwg_full.services.broker import RemoteSemantic
from rcwg_full.auto2.host import delegated_driver


def run(request):
    if request['source_hash']!=digest(source_hashes()):raise PermissionError('REMOTE_SOURCE_CHANGED')
    task=json.loads(read(Path(request['data_directory'])/'task_public.json'))
    manifest=Path(request['data_directory'])/'data_manifest.json'
    if digest(task)!=request['task_hash'] or sha(read(manifest))!=request['manifest_hash']:raise PermissionError('REMOTE_DATA_CHANGED')
    service=None
    if request.get('semantic_connection'):
        service=RemoteSemantic(request['semantic_connection']);service.client=SimpleNamespace(binding=request['service_binding'])
    driver=None
    if request.get('host_scope'):
        scope=json.loads(read(request['host_scope']));authority=json.loads(read(request['authority']))
        if digest(scope)!=request['host_scope_hash']:raise PermissionError('HOST_SCOPE_CHANGED')
        driver=delegated_driver(scope,authority,task,request['build'],request['attempt_id'])
    report=execute(task,request['plan'],manifest,build=request['build'],output=request['output'],mode='LIVE_DEVELOPMENT',
        condition_id=request['condition'],driver=driver,semantic_service=service,verify=None,
        record_role=request.get('record_role','MODEL'),generation_id=request.get('generation_id'))
    # This process cannot read gold. The controller verifies result.json afterward.
    return {'terminal_status':report['terminal_status'],'output':request['output'],'report_hash':sha(read(Path(request['output'])/'report.json'))}


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);a=p.parse_args()
    print(json.dumps(run(json.loads(read(a.request)))))

if __name__=='__main__':main()
