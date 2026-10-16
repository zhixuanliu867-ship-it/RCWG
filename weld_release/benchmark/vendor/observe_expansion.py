"""Execute registered probes against a selected snapshot; contains no gold values."""
from pathlib import Path
import sys,json,io
repo=Path(sys.argv[1]);family=sys.argv[2];check=sys.argv[3]
sys.path.insert(0,str(repo/'src'))
cases=json.loads((repo/'REGISTERED_INPUTS.json').read_text(encoding='utf8'))[check]
out=[]
for case in cases:
 try:
  if family=='packaging':
   from packaging.specifiers import SpecifierSet
   from packaging.version import Version
   if check=='version_normalization':value=str(Version(case['value']))
   else:value=SpecifierSet(case['spec']).contains(case['value'],prereleases=True)
  else:
   if check=='parser_records':
    from dotenv.parser import parse_stream
    value=[{'key':b.key,'value':b.value,'error':b.error} for b in parse_stream(io.StringIO(case['value']))]
   else:
    from dotenv import dotenv_values
    value=dict(dotenv_values(stream=io.StringIO(case['value']),interpolate=False))
  outcome=json.dumps(value,sort_keys=True,ensure_ascii=False)
 except Exception as e:outcome='raises:'+type(e).__name__
 out.append({'case_id':case['id'],'observed_outcome':outcome})
print(json.dumps({'check':check,'observations':out},ensure_ascii=False))
