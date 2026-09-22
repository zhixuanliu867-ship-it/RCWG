"""Reproducible COMPAT1 wire schemas. Semantic compilation remains mandatory."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rcwg_full.compiler.operators import BINDABLE
from rcwg_full.services.bindings import FIELDS,SLOTS


def object_schema(properties,required=None):
    return {'type':'object','additionalProperties':False,'required':list(properties) if required is None else required,'properties':properties}


def schemas():
    legacy=ROOT/'specs/reference_v1_0/schemas/workflow.schema.json'
    workflow=json.loads(legacy.read_text('utf8'));workflow['$id']='urn:rcwg:workflow:full001:compat1'
    workflow['title']='RCWG_FULL001_COMPAT1 WorkIR structural schema'
    workflow['$comment']='This schema checks wire structure only. FullCompiler enforces types, public source capabilities, limits, dependencies and all operator parameter semantics.'
    operators=json.loads((ROOT/'specs/full001/operators.json').read_text('utf8'))['operators']
    string={'type':'string','minLength':1};hash_string={'type':'string','pattern':'^[0-9a-f]{64}$'}
    binding=object_schema({'parameter':{'type':'string','pattern':'^[a-z][a-z0-9_]{0,47}$'},'ref':string,'field':string},['parameter','ref'])
    workflow['$defs']['parameter_binding']=binding
    node=workflow['$defs']['node'];node['properties']['param_bindings']={'type':'array','items':{'$ref':'#/$defs/parameter_binding'}}
    node['allOf']=[]
    for op in operators:
        name=op['operator_id'];fields=BINDABLE.get(name,{})
        limits={'type':'array','maxItems':len(fields),'items':{'allOf':[{'$ref':'#/$defs/parameter_binding'},
                    {'properties':{'parameter':{'enum':list(fields)}}}]}} if fields else {'type':'array','maxItems':0}
        node['allOf'].append({'if':{'properties':{'operator':{'const':name}}},'then':{'properties':{
            'implementation':{'enum':op['implementations']},'param_bindings':limits}}})
    caps={k:{'enum':['SUPPORTED','UNSUPPORTED','UNKNOWN']} for k in ['seed','temperature','top_k','thinking','json']}
    properties={'slot':{'enum':list(SLOTS)},'role':{'enum':['GENERATOR','EXECUTOR']},'provider':{'const':'VERTEX'},
        'endpoint':{'type':'string','pattern':'^https://'},'api_version':{'const':'v1'},'requested_model':string,
        'reported_revision':{'type':['string','null']},'region':string,'account_binding_hash':hash_string,
        'supported_parameters':object_schema(caps),'max_input_tokens':{'type':'integer','minimum':12288},
        'max_output_tokens':{'type':'integer','minimum':1},'thinking':{'type':['boolean','null']},
        'structured_json':{'type':'boolean'},'tokenizer':{'type':['string','null']},
        'count_method':{'enum':['PROVIDER_COUNT','LOCAL_TOKENIZER','UNKNOWN']},
        'price_snapshot':{'type':['object','null']},'data_policy':{'type':['string','object','null']},
        'valid_from':{'type':['string','null']},'valid_until':{'type':['string','null']},
        'decoding':object_schema({'temperature':{'type':['number','null'],'minimum':0,'maximum':2},
            'top_k':{'type':['integer','null'],'minimum':1},'thinking':{'type':['object','null']}},[]),
        'idempotency':{'enum':['UNSUPPORTED','UNKNOWN']},'template_hash':hash_string}
    assert set(properties)==FIELDS
    service={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:rcwg:services:full001:1',
       'title':'FULL001 service binding; live validation and receipts are separate',**object_schema(properties),
       'allOf':[{'if':{'properties':{'slot':{'pattern':'^G'}}},'then':{'properties':{'role':{'const':'GENERATOR'},'max_output_tokens':{'minimum':16384}}},
                 'else':{'properties':{'role':{'const':'EXECUTOR'}}}}]}
    receipt={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:rcwg:receipt:full001:1',
       **object_schema({'approved':{'const':True},'action':{'enum':['HOST','PAID_SERVICES','FORMAL_LAUNCH','AUDIT_UNSEAL']},
          'subject_hash':hash_string,'actor_role':{'enum':['Owner','Auditor']},'actor_id':string,'receipt_id':string,
          'valid_from':{'type':'string','format':'date-time'},'valid_until':{'type':'string','format':'date-time'}}),
       '$comment':'Schema validity is not authorization. Trusted receipt provenance, exact action/role/scope and current validity must be checked separately.'}
    capability={'schema_version':'FULL001_CAPABILITY_MANIFEST_1','profile':'RCWG_FULL001_COMPAT1',
       'legacy_schema_sha256':hashlib.sha256(legacy.read_bytes()).hexdigest(),
       'operators':[{ 'operator':op['operator_id'],'implementations':op['implementations'],
          'bindable_value_parameters':{k:v[0] for k,v in BINDABLE.get(op['operator_id'],{}).items()}} for op in operators],
       'limits':{'recursive_nodes':48,'region_depth':2,'loop_iterations':16,'cumulative_node_instances':4096,'final_json_bytes':65536},
       'extensions':['project.views_expressions_record_pack','typed_parameter_bindings','top_k.partition_by','text_retrieve.offset','semantic_extract.question'],
       'validation_entrypoint':'rcwg_full.compiler.FullCompiler.compile',
       'original_profile_entrypoint':'rcwg_spec.compiler.validate_workflow','select_profile_outside_model_output':True,
       'formal_ready':False,'status':'DECLARED_SOFTWARE_CAPABILITIES_NOT_DISPATCH_EVIDENCE'}
    return {'workflow.compat1.schema.json':workflow,'service-binding.schema.json':service,'receipt.schema.json':receipt,'capabilities.json':capability}


def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    destination=ROOT/'specs/full001/schemas'
    if not args.check:destination.mkdir(parents=True,exist_ok=True)
    failed=[]
    for name,value in schemas().items():
        raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf8');path=destination/name
        if args.check:
            if not path.is_file() or path.read_bytes()!=raw:failed.append(name)
        else:path.write_bytes(raw)
    print(json.dumps({'phase':'SCHEMA_REPRODUCIBILITY','status':'FAIL' if failed else 'PASS','mismatches':failed}))
    return int(bool(failed))


if __name__=='__main__':raise SystemExit(main())
