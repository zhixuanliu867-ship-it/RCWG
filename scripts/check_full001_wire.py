from pathlib import Path
import sys,json,hashlib,platform,importlib.metadata as metadata
from copy import deepcopy
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
repo=Path(__file__).resolve().parents[1];sys.path.insert(0,str(repo));sys.path.insert(0,str(repo/'acceptance/full001'))
import jsonschema,yaml
from rcwg_full.evidence import source_hashes,digest
from rcwg_full.data.templates import f1
from rcwg_full.data.relational_f2 import f2
from rcwg_full.data.graph_templates import f3
from rcwg_full.data.stream_templates import f4
from rcwg_full.data.document_templates import f5
from rcwg_full.data.mixed_templates import f6
from test_services import binding
from rcwg_full.services.requests import assemble
root=repo/'specs/full001/schemas';schemas={p.name:json.loads(p.read_text('utf8')) for p in root.glob('*.schema.json')}
for s in schemas.values():jsonschema.Draft202012Validator.check_schema(s)
validator=jsonschema.Draft202012Validator(schemas['workflow.compat1.schema.json']);tests=[]
for family,builder in enumerate([f1,f2,f3,f4,f5,f6],1):
 for number in range(1,13):
  for base in range(5):
   for condition in ['C0','C1','C2','C3']:
    bundle=builder(f'F{family}-{number:02d}',base,condition);validator.validate(bundle['plan'])
    tests.append({'id':bundle['task']['task_id'],'status':'PASS','plan_sha256':digest(bundle['plan'])})
plan=f1('F1-01',0,'C0')['plan'];bad=deepcopy(plan);bad['nodes'][0]['implementation']='not-registered'
assert list(validator.iter_errors(bad));bad=deepcopy(plan);bad['nodes'][0]['param_bindings']=[{'parameter':'source','ref':'x.rows'}]
assert list(validator.iter_errors(bad));bad=deepcopy(plan);bad['provider']='forbidden';assert list(validator.iter_errors(bad))
for slot in [*[f'G{i}' for i in range(6)],'E0','E1']:jsonschema.validate(binding(slot),schemas['service-binding.schema.json'])
workflow=yaml.safe_load((repo/'configs/full001/control_workflow.yaml').read_text('utf8'))
assert workflow['main']['params']==['args'];steps={k:v for row in workflow['main']['steps'] for k,v in row.items()}
assert {'submit','inspect','request_cancel','artifacts','done'}<=steps.keys()
assert 'retry' not in steps['submit'];assert steps['submit']['try']['args']['headers']['Idempotency-Key']=='${args.idempotency_key}'
assert steps['submit']['except']['steps'][0]['reconcile_submission']['call']=='http.get'
request=assemble(f1('F1-01',0,'C0')['task'],binding(),protocol='P0',stage='physical',attempt_id='fixture',request_id='00000000-0000-4000-8000-000000000001',trial_label=17)
out=args.output;out.mkdir(parents=True,exist_ok=False)
report={'scope':'JSON_SCHEMA_WIRE_AND_YAML_SYNTAX_ONLY_NOT_NATIVE_OR_CLOUD_ACCEPTANCE','status':'PASS',
 'command':[sys.executable,*sys.argv],'python':platform.python_version(),'jsonschema':metadata.version('jsonschema'),'PyYAML':metadata.version('PyYAML'),
 'source_hash':digest(source_hashes()),'template_plan_checks':len(tests),'tests':tests,'invalid_variants_rejected':3,
 'service_bindings_validated':8,'workflow_syntax':'PARSED_OFFLINE_NOT_DEPLOYED','sample_public_request':{
 'input_bytes':request['input_bytes'],'input_characters':request['input_characters'],'provider_tokens':None},'formal_ready':False}
(out/'REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='tests'}))
