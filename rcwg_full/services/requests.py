"""Public generation assembly; P1 stages remain distinct physical requests."""
from pathlib import Path
import json
import re
from rcwg_full.evidence import ROOT,canonical,digest,read,sha
from rcwg_full.compiler.public_task import validate_public_task
from rcwg_spec.generation import validate_logical_contract,parse_response,TOKEN_LIMITS
from .bindings import validate_binding


def assemble(task, binding, *, protocol, stage, attempt_id, request_id, trial_label,
             logical=None, guidance=None):
    b=validate_binding(binding)
    if (protocol,stage) not in TOKEN_LIMITS:raise ValueError('GENERATION_STAGE')
    if trial_label not in {17,29}:raise ValueError('GENERATION_TRIAL')
    checked=validate_public_task(task)
    if protocol=='P1' and stage=='physical':logical=validate_logical_contract(logical)
    elif logical is not None:raise ValueError('LOGICAL_UNEXPECTED')
    source_names=['prompts/v1_1/system.txt','prompts/v1_1/'+('p0_user.txt' if protocol=='P0' else 'p1_'+stage+'.txt'),
                  'specs/reference_v1_0/catalogs/operators.json','specs/full001/schemas/workflow.compat1.schema.json',
                  'specs/reference_v1_0/examples/workflow_topk.json','specs/spec001b/generation_schema_addendum.json',
                  'specs/spec001b/operator_contract_worklist.json','specs/full001/operators.json','specs/full001/defaults.json',
                  'prompts/full001/compat1.txt']
    sources={name:read(ROOT/name) for name in source_names}
    replacements={'task_json':canonical(checked['normalized_task']).decode(),
       'operator_catalog':canonical(json.loads(sources[source_names[2]])).decode(),'workflow_schema':canonical(json.loads(sources[source_names[3]])).decode(),
       'example_json':canonical(json.loads(sources[source_names[4]])).decode(),'logical_contract':canonical(logical).decode() if logical is not None else ''}
    rendered=re.sub(r'\{\{([a-z_]+)\}\}',lambda m:replacements[m.group(1)],sources[source_names[1]].decode())
    worklist=json.loads(sources[source_names[6]])
    planning={'operator','implementations','input_ports','output_ports','required_parameters','optional_parameters','static_rules'}
    supplement={'profile':'RCWG_FULL001_COMPAT1','operators':[{k:v for k,v in r.items() if k in planning} for r in worklist['operators']],
                'compatibility_extensions':json.loads(sources[source_names[8]])['compatibility_extensions']}
    messages=[{'role':'system','content':sources[source_names[0]].decode()},
              {'role':'system','content':sources[source_names[5]].decode()},
              {'role':'system','content':canonical(supplement).decode()},
              {'role':'system','content':sources['prompts/full001/compat1.txt'].decode()},
              {'role':'user','content':rendered}]
    if guidance is not None:
        from rcwg_full.campaign.transforms import public_guidance
        if guidance!=public_guidance(task):raise ValueError('PUBLIC_GUIDANCE_IDENTITY')
        messages.append({'role':'user','content':canonical(guidance).decode()})
    config={'maxOutputTokens':TOKEN_LIMITS[protocol,stage],'candidateCount':1}
    if b['structured_json'] and b['supported_parameters']['json']=='SUPPORTED':config['responseMimeType']='application/json'
    for key,wire in [('temperature','temperature'),('top_k','topK')]:
        if b['decoding'].get(key) is not None:config[wire]=b['decoding'][key]
    if b['decoding'].get('thinking') is not None:config['thinkingConfig']=b['decoding']['thinking']
    if b['supported_parameters']['seed']=='SUPPORTED':config['seed']=trial_label
    body={'systemInstruction':{'parts':[{'text':m['content']} for m in messages if m['role']=='system']},
          'contents':[{'role':'user','parts':[{'text':m['content']}]} for m in messages if m['role']=='user'],'generationConfig':config}
    return {'schema_version':'FULL001_REQUEST_1','generation_attempt_id':attempt_id,'request_id':request_id,
            'protocol':protocol,'stage':stage,'slot':b['slot'],'binding_hash':digest(b),'body':body,'body_hash':digest(body),
            'source_hashes':{name:sha(raw) for name,raw in sources.items()},'task_hash':digest(task),
            'trial_label':trial_label,'seed_sent':config.get('seed'),'max_input_tokens':12288,
            'max_output_tokens':TOKEN_LIMITS[protocol,stage],'max_json_bytes':65536,
            'input_bytes':len(canonical(body)),'input_characters':len(canonical(body).decode()),
            'reference_token_count':None,'provider_usage':None,'formal_ready':False}


def parse_final(raw,stage,*,allow_single_fence=False):
    if type(raw) is not bytes:raise ValueError('RESPONSE_BYTES')
    original=sha(raw)
    if allow_single_fence:
        text=raw.decode('utf-8')
        match=re.fullmatch(r'\s*```(?:json)?\s*\n(.*?)\n```\s*',text,re.DOTALL)
        if match:raw=match.group(1).encode('utf-8')
    parsed=parse_response(raw,kind=stage)
    return {**parsed,'provider_text_sha256':original,'single_fence_removed':sha(raw)!=original}
