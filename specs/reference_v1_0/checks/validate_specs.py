from pathlib import Path
import json
from jsonschema import Draft202012Validator
ROOT = Path(__file__).resolve().parents[1]
load=lambda p: json.loads((ROOT/p).read_text(encoding="utf-8"))
schema=load("schemas/workflow.schema.json")
Draft202012Validator.check_schema(schema)
v=Draft202012Validator(schema)
ops={x["operator"]:x for x in load("catalogs/operators.json")}
for p in sorted((ROOT/"examples").glob("workflow*.json")):
    w=json.loads(p.read_text(encoding="utf-8"));v.validate(w)
    ids={n["id"] for n in w["nodes"]}
    assert len(ids)==len(w["nodes"]), "duplicate node id"
    dep={n["id"]:set(n.get("after",[])) for n in w["nodes"]}
    for n in w["nodes"]:
        assert n["implementation"] in ops[n["operator"]]["implementations"]
        for ref in n["inputs"].values():
            if ref.startswith("$input."):
                assert ref.split(".",1)[1] in w["external_inputs"]
            else:
                parent,port=ref.split(".",1)
                assert parent in ids
                pn=next(k for k in w["nodes"] if k["id"]==parent)
                assert port in pn["outputs"]
                dep[n["id"]].add(parent)
    done=set()
    while len(done)<len(ids):
        ready={k for k,d in dep.items() if k not in done and d<=done}
        assert ready,"cycle or missing dependency"
        done |= ready
    print("PASS",p.name)
c=load("configs/campaign.json")
assert 48*5*4 == 960
assert 960*6*2*2 == c["expected_counts"]["generation_attempts"]
assert 640*6*2*2*3 == c["expected_counts"]["deterministic_execution_attempts"]
assert 320*6*2*2*2 == c["expected_counts"]["semantic_execution_attempts"]
print("PASS formal matrix counts")
print("NOTE: schema/examples checks only; runtime, models, datasets and benchmark are not implemented here.")
