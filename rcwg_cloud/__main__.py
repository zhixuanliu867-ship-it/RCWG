"""Cloud-only production entry; no simulation, alternate project or retry flag."""
import json,os,re,sys,tempfile
from pathlib import Path
from rcwg_api.common import strict
from rcwg_spec.common import canonical
from .contracts import manifest,authorization,sha
from .transport import MetadataIdentity,CloudHTTP,GCSStore,VertexCloud,CloudError
from .runtime import load_object,run_batch
from .source import verify

def main():
    if len(sys.argv)!=1:raise CloudError('NO_COMMAND_LINE_OVERRIDE')
    phase=os.environ.get('RCWG_CLOUD_PHASE')
    if phase not in ('replay','live'):raise CloudError('PHASE_REQUIRED')
    identity=MetadataIdentity();observed_identity=identity.verify(phase)
    execution=os.environ.get('CLOUD_RUN_EXECUTION','')
    if not re.fullmatch('rcwg-cloud001-'+phase+'-[a-z0-9-]+',execution):raise CloudError('EXECUTION_IDENTITY')
    expected=sha(os.environ.get('RCWG_MANIFEST_SHA256'))
    generation=os.environ.get('RCWG_MANIFEST_GENERATION')
    if type(generation) is not str or not re.fullmatch('[1-9][0-9]{0,30}',generation):raise CloudError('MANIFEST_GENERATION_REQUIRED')
    store=GCSStore(CloudHTTP(identity))
    raw,receipt=load_object(store,{'object':'cloud001/manifests/'+phase+'.json','generation':generation,'sha256':expected})
    m=manifest(strict(raw),phase)
    if canonical(m)!=raw:raise CloudError('MANIFEST_CANONICAL_BYTES_REQUIRED')
    if os.environ.get('RCWG_IMAGE_DIGEST')!=m['image_digest']:raise CloudError('DECLARED_IMAGE_DIGEST_MISMATCH')
    source=verify(Path(__file__).resolve().parents[1],m['image_source_sha256'])
    approval=strict(load_object(store,m['approval'])[0]);pricing=c1=None
    if phase=='live':
        pricing=strict(load_object(store,m['pricing'])[0]);c1=strict(load_object(store,m['c1_review'])[0])
    checked=authorization(m,approval,pricing,c1)
    context={'mode':'ACTUAL_CLOUD_SERVICE_RUNTIME_SELF_OBSERVATION','identity':observed_identity,'authorization':checked,'source':source,
             'manifest_receipt':receipt,'image_digest_declared':m['image_digest'],'actual_oci_image':'REQUIRES_INDEPENDENT_CONTROL_PLANE_VERIFICATION',
             'execution':execution,'job':os.environ['CLOUD_RUN_JOB'],'task_index':0,'task_count':1,'task_attempt':0}
    work=Path(tempfile.mkdtemp(prefix='rcwg-cloud001-'))/'evidence'
    result=run_batch(m,store=store,vertex=VertexCloud(store.http) if phase=='live' else None,root=work,execution_id=execution,context=context)
    # Cloud Logging gets a small status only. Raw model/evidence remains private GCS.
    print(json.dumps({'version':'CLOUD001_LOG_STATUS_1','phase':phase,'execution_id':execution,'status':result['status'],
                      'formal_ready':False,'independent_review':'PENDING'}),flush=True)
    return 0 if result['status'] in ('REPLAY_RUNTIME_OBSERVED_EXPECTED','LIVE_RUNTIME_OBSERVED_COMPLETE') else 2

if __name__=='__main__':
    try:code=main()
    except Exception as e:
        print(json.dumps({'status':'CLOUD001_ENTRY_FAILED','exception_type':type(e).__name__,'code':str(e) if type(e) is CloudError else 'ENTRY_FAILURE',
                          'independent_reconciliation_required':True,'formal_ready':False}),flush=True);code=2
    sys.exit(code)
