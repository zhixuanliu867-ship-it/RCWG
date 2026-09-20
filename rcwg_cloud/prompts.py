"""Versioned final-wire parity; protected v1.1 serializers stay unchanged."""
from pathlib import Path
from copy import deepcopy
import hashlib,json
from rcwg_spec.common import canonical,digest,ContractError
from rcwg_spec.public_task import validate_public_task
from rcwg_spec.generation import TOKEN_LIMITS,validate_logical_contract,build_request as legacy_request
from rcwg_api.policy import default_config
from rcwg_api.vertex import make_body,count_body

ROOT=Path(__file__).resolve().parents[1]
PROFILE='CLOUD001_PROMPTS_1_PROTO_PATCH_AUDIT_F01'
SOURCE_PATHS={
 'system':'prompts/v1_1/system.txt',
 'contract':'prompts/cloud001_v1/common_workir_contract.md',
 'schema':'specs/reference_v1_0/schemas/workflow.schema.json',
 'catalog':'specs/reference_v1_0/catalogs/operators.json',
 'example':'specs/reference_v1_0/examples/workflow_topk.json',
 'addendum':'specs/spec001b/generation_schema_addendum.json',
 'worklist':'specs/spec001b/operator_contract_worklist.json'}

def common_parts():
    raw={k:(ROOT/v).read_bytes() for k,v in SOURCE_PATHS.items()}
    worklist=json.loads(raw['worklist'])
    fields={'operator','implementations','input_ports','output_ports','required_parameters',
            'optional_parameters','static_rules','runtime_obligations'}
    approved={'operators':[{k:v for k,v in row.items() if k in fields} for row in worklist['operators']]}
    parts=[raw['system'].decode('utf-8'),raw['contract'].decode('utf-8'),
           raw['addendum'].decode('utf-8'),'WORKIR SCHEMA\n'+raw['schema'].decode('utf-8'),
           'PUBLIC OPERATOR CATALOG\n'+raw['catalog'].decode('utf-8'),
           'APPROVED OPERATOR CONTRACTS\n'+canonical(approved).decode('utf-8'),
           'SHARED PUBLIC DEVELOPMENT EXAMPLE\n'+raw['example'].decode('utf-8')]
    return parts,{SOURCE_PATHS[k]:hashlib.sha256(v).hexdigest() for k,v in raw.items()}

def physical_body(task,protocol,logical=None):
    if protocol not in ('P0','P1'):raise ContractError('GENERATION_STAGE','/protocol','unsupported physical protocol')
    checked=validate_public_task(task)
    if protocol=='P1':logical=validate_logical_contract(logical)
    elif logical is not None:raise ContractError('LOGICAL_UNEXPECTED','/logical','P0 cannot receive a logical-stage output')
    shared,sources=common_parts()
    public={'task':checked['normalized_task'],'instruction':'Generate the physical WorkIR satisfying the public TASK.'}
    if protocol=='P1':public['logical_contract']=logical
    messages=[{'role':'system','content':p} for p in shared]+[{'role':'user','content':canonical(public).decode('utf-8')}]
    assembled={'protocol':protocol,'stage':'physical','provider_payload':{'messages':messages}}
    body=make_body(assembled,default_config('rcwg-509116'))
    # The final profile is explicit; no API001 identity/authentication is inherited.
    body['systemInstruction']['parts'][-1]['text']=body['systemInstruction']['parts'][-1]['text'].replace('API001 ENGINEERING PROFILE.','CLOUD001 ENGINEERING PROFILE.',1)
    evidence={'profile':PROFILE,'protocol':protocol,'stage':'physical','sources':sources,
              'common_parts_sha256':digest(body['systemInstruction']['parts']),
              'task_input_hash':checked['task_input_hash'],'normalized_task_sha256':digest(checked['normalized_task']),
              'logical_contract_sha256':digest(logical) if logical is not None else None,
              'provider_body_sha256':digest(body),'provider_body_bytes':len(canonical(body)),
              'max_input_tokens':12288,'max_output_tokens':TOKEN_LIMITS[(protocol,'physical')],
              'formal_ready':False,'real_model_requests':0}
    if evidence['provider_body_bytes']>131072:raise ContractError('REQUEST_BYTE_LIMIT','','bounded final provider body required')
    return body,evidence

def logical_body(task):
    # Logical-stage protocol/token allocation unchanged, marked as the new batch.
    assembled=legacy_request(task,protocol='P1',stage='logical',generation_attempt_id='cloud001.p1.g0',request_id='cloud001.p1.g0.logical')
    body=make_body(assembled,default_config('rcwg-509116'))
    body['systemInstruction']['parts'][-1]['text']=body['systemInstruction']['parts'][-1]['text'].replace('API001 ENGINEERING PROFILE.','CLOUD001 ENGINEERING PROFILE.',1)
    return body,{'profile':PROFILE,'stage':'logical','provider_body_sha256':digest(body),'source_hashes':assembled['source_hashes']}

def audit_physical_parity(p0,p1,task,logical):
    """Check final provider objects, not a registry claiming unused source hashes."""
    expected0,ev0=physical_body(task,'P0');expected1,ev1=physical_body(task,'P1',logical)
    if p0!=expected0 or p1!=expected1:raise ContractError('FINAL_PROVIDER_PARITY_MISMATCH','','final provider objects differ from approved assembly')
    if p0['systemInstruction']!=p1['systemInstruction']:raise ContractError('COMMON_MATERIAL_MISMATCH','','physical common parts differ')
    u0=json.loads(p0['contents'][0]['parts'][0]['text']);u1=json.loads(p1['contents'][0]['parts'][0]['text'])
    if u0['task']!=u1['task'] or u1['logical_contract']!=logical:raise ContractError('PUBLIC_TASK_OR_LOGICAL_MISMATCH','','task or logical response changed')
    if '$input.' not in canonical(p0['systemInstruction']).decode('utf-8'):raise ContractError('REFERENCE_GRAMMAR_MISSING','','actual body lacks reference syntax')
    return {'status':'FINAL_PROVIDER_PHYSICAL_PARITY_PASS','common_parts_sha256':ev0['common_parts_sha256'],
            'p0_body_sha256':digest(p0),'p1_body_sha256':digest(p1),'logical_contract_sha256':digest(logical),
            'source_hashes':ev0['sources'],'real_model_requests':0,'formal_ready':False}
