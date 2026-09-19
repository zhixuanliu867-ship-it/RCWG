"""Unit-checked observed-resource records and fail-closed per-repeat scoring.

Reference comparisons are relative to frozen confirmed candidates, not global optima.
No computation here starts a model, executes WorkIR, or measures remote hardware.
"""
from decimal import Decimal
from statistics import mean
from collections import defaultdict
from .common import ContractError, keys, number, text, digest

CATALOG={
 "wall_s":("s","worker_exec"),
 "cpu_s":("s","worker_exec"),
 "memory_peak_bytes":("byte","worker_cgroup"),
 "logical_read_bytes":("byte","artifact_proxy"),
 "copy_bytes":("byte","artifact_proxy"),
 "wire_bytes":("byte","transport"),
 "semantic_requests":("count","semantic_service"),
 "semantic_tokens_reference":("token","semantic_service"),
}
OBS_STATUS={"MEASURED","CENSORED","UNAVAILABLE","NOT_APPLICABLE"}
RUN_STATUS={"COMPLETED","TASK_FAILURE","INVALID_PLAN","TIMEOUT","OOM","EXECUTION_ERROR","REFUSAL","INFRA_FAILURE","CANCELLED","MISSING_EVIDENCE"}
FAILURES={"TASK_FAILURE","INVALID_PLAN","TIMEOUT","OOM","EXECUTION_ERROR","REFUSAL"}
UNKNOWN={"INFRA_FAILURE","CANCELLED","MISSING_EVIDENCE"}
HIERARCHY=("family","template_id","base_id","condition_id","generation_id","repeat_id")
REQUIRED={"record_id","model_id","protocol","case_id","budget",*HIERARCHY}

def measurement(value,unit,scope,status="MEASURED",reason=None):
    return {"value":value,"unit":unit,"scope":scope,"status":status,"reason":reason}

def validate_measurement(name,m):
    if name not in CATALOG:raise ContractError("UNKNOWN_METRIC",name,"not a capability resource")
    keys(m,{"value","unit","scope","status","reason"},set(),name)
    if (m["unit"],m["scope"])!=CATALOG[name]:
        raise ContractError("METRIC_UNIT_SCOPE",name,"unit or scope mismatch")
    if not isinstance(m["status"],str) or m["status"] not in OBS_STATUS:raise ContractError("METRIC_STATUS",name,"unknown status")
    if m["status"] in {"MEASURED","CENSORED"}:
        number(m["value"],name+".value")
        if CATALOG[name][0] in {"byte","count","token"}:number(m["value"],name+".value",integer=True)
    elif m["value"] is not None:raise ContractError("MISSING_MUST_BE_NULL",name,"missing observations never use zero")
    if m["status"]=="MEASURED" and m["reason"] is not None:raise ContractError("MEASURED_REASON",name,"reason must be null")
    if m["status"]!="MEASURED":text(m["reason"],name+".reason")

def validate_expected(e):
    keys(e,REQUIRED,set(),"manifest[]")
    for k in REQUIRED-{"budget"}:text(e[k],f"manifest[].{k}")
    if not isinstance(e["budget"],dict) or not {"wall_s","memory_peak_bytes"}<=e["budget"].keys():
        raise ContractError("BUDGET_REQUIRED","manifest[].budget","wall_s and memory_peak_bytes required")
    for k,v in e["budget"].items():
        if k not in CATALOG:raise ContractError("UNKNOWN_BUDGET",k,"monetary cost is not a primary capability budget")
        number(v,k,positive=True,integer=CATALOG[k][0] in {"byte","count","token"})

def validate_observation(o):
    keys(o,{"record_id","status","semantic_pass","metrics","evidence_id","reason"},set(),"observations[]")
    text(o["record_id"],"record_id");text(o["evidence_id"],"evidence_id")
    if not isinstance(o["status"],str) or o["status"] not in RUN_STATUS:raise ContractError("RUN_STATUS","status","unknown terminal state")
    if o["semantic_pass"] is not None and type(o["semantic_pass"]) is not bool:
        raise ContractError("SEMANTIC_STATUS","semantic_pass","bool or null required")
    if not isinstance(o["metrics"],dict):raise ContractError("OBJECT_REQUIRED","metrics","expected map")
    for name,m in o["metrics"].items():validate_measurement(name,m)
    if o["status"]!="COMPLETED" or o["semantic_pass"] is None:text(o["reason"],"reason")
    elif o["reason"] is not None:text(o["reason"],"reason")
    if o["status"] in FAILURES and o["semantic_pass"] is True:
        raise ContractError("CONTRADICTORY_OUTCOME","semantic_pass","failure cannot claim semantic success")

def tri_and(values):
    if any(v is False for v in values):return False
    return None if any(v is None for v in values) else True

def _bound(m,limit):
    if m is None or m["status"] in {"UNAVAILABLE","NOT_APPLICABLE"}:return None
    if m["status"]=="CENSORED":return False if m["value"]>limit else None
    return m["value"]<=limit

def score_repeat(expected,observed,reference=None,epsilon=0.20):
    validate_expected(expected);number(epsilon,"epsilon")
    if observed is None:
        observed={"record_id":expected["record_id"],"status":"MISSING_EVIDENCE","semantic_pass":None,"metrics":{},"evidence_id":"missing-record","reason":"EXPECTED_MANIFEST_RECORD_ABSENT"}
    validate_observation(observed)
    if expected["record_id"]!=observed["record_id"]:raise ContractError("RECORD_MISMATCH","record_id","unexpected ID")
    checks={k:_bound(observed["metrics"].get(k),v) for k,v in expected["budget"].items()}
    status=observed["status"]
    if status=="TIMEOUT":checks["wall_s"]=False
    if status=="OOM":checks["memory_peak_bytes"]=False
    B=tri_and(checks.values())
    S=False if status in FAILURES else (None if status in UNKNOWN else observed["semantic_pass"])
    V=None if status in UNKNOWN else tri_and([S,B])
    missing=[k for k,v in checks.items() if v is None]
    covered=False;ref_t=None
    if reference is not None:
        keys(reference,{"case_id","budget_hash","time_s","confirmation_id","frozen"},set(),"reference")
        text(reference["confirmation_id"],"reference.confirmation_id")
        if reference["case_id"]!=expected["case_id"] or reference["budget_hash"]!=digest(expected["budget"]):
            raise ContractError("REFERENCE_SCOPE","reference","case/budget mismatch")
        if reference["frozen"] is not True:raise ContractError("REFERENCE_NOT_FROZEN","reference","frozen confirmation required")
        ref_t=number(reference["time_s"],"reference.time_s",positive=True);covered=True
    rho=None;near=None
    wall=observed["metrics"].get("wall_s")
    if covered and wall is not None and wall["status"]=="MEASURED":
        rho=wall["value"]/ref_t
        near=Decimal(str(wall["value"])) <= (Decimal(1)+Decimal(str(epsilon)))*Decimal(str(ref_t))
    efficient=tri_and([V,near]) if covered and status not in UNKNOWN else None
    return {"record_id":expected["record_id"],"S":S,"B":B,"V":V,"budget_checks":checks,
            "missing_budget_metrics":missing,"reference_covered":covered,"time_ratio":rho,
            "efficient_success":efficient,"terminal_status":status,
            "evidence_state":"MISSING" if status in UNKNOWN else ("PARTIAL" if missing else "COMPLETE_FOR_DECLARED_BUDGETS")}

def _hierarchical(rows,field,level=0):
    # Unknowns produce identification bounds, not confidence intervals.
    if level==len(HIERARCHY):
        values=[s[field] for _,s in rows]
        return (mean(0.0 if v is None else float(v) for v in values),mean(1.0 if v is None else float(v) for v in values))
    groups=defaultdict(list)
    for e,s in rows:groups[e[HIERARCHY[level]]].append((e,s))
    scores=[_hierarchical(g,field,level+1) for g in groups.values()]
    return mean(s[0] for s in scores),mean(s[1] for s in scores)

def _summary(rows,field):
    if not rows:return {"point":None,"lower":None,"upper":None,"status":"NO_ELIGIBLE_CASES"}
    low,high=_hierarchical(rows,field)
    return {"point":low if low==high else None,"lower":low,"upper":high,"status":"COMPLETE" if low==high else "PARTIALLY_IDENTIFIED"}

def score_manifest(manifest,observations,references,epsilon=0.20):
    if not isinstance(manifest,list) or not manifest:raise ContractError("EMPTY_MANIFEST","manifest","predeclared records required")
    if not isinstance(observations,list) or not isinstance(references,list):raise ContractError("ARRAY_REQUIRED","inputs","observations and references must be arrays")
    for e in manifest:validate_expected(e)
    ids=[e["record_id"] for e in manifest]
    if len(ids)!=len(set(ids)):raise ContractError("DUPLICATE_RECORD","manifest","duplicate record_id")
    expected_coords=[tuple(e[k] for k in ("model_id","protocol",*HIERARCHY)) for e in manifest]
    if len(set(expected_coords))!=len(expected_coords):raise ContractError("DUPLICATE_COORDINATES","manifest","repeat coordinates must be unique")
    expected_cases={}
    for e in manifest:
        bh=digest(e["budget"])
        if e["case_id"] in expected_cases and expected_cases[e["case_id"]]!=bh:
            raise ContractError("CASE_BUDGET_MISMATCH","manifest","one case_id must have one budget")
        expected_cases[e["case_id"]]=bh
    by_id={}
    for o in observations:
        validate_observation(o)
        if o["record_id"] in by_id:raise ContractError("DUPLICATE_RECORD","observations","duplicate record_id")
        if o["record_id"] not in ids:raise ContractError("UNPLANNED_RECORD","observations","record not in manifest")
        by_id[o["record_id"]]=o
    refs={}
    for ref in references:
        if not isinstance(ref,dict) or "case_id" not in ref:raise ContractError("REFERENCE_SCOPE","reference","case_id required")
        text(ref["case_id"],"reference.case_id")
        if ref["case_id"] in refs:raise ContractError("DUPLICATE_REFERENCE","references","one confirmed reference per case")
        if ref["case_id"] not in expected_cases:raise ContractError("UNPLANNED_REFERENCE","references","case absent in manifest")
        refs[ref["case_id"]]=ref
    panels=defaultdict(list);results=[]
    for e in manifest:
        s=score_repeat(e,by_id.get(e["record_id"]),refs.get(e["case_id"]),epsilon)
        panels[(e["model_id"],e["protocol"])].append((e,s));results.append(s)
    case_sets=[{e["case_id"] for e,_ in rows} for rows in panels.values()]
    comparable=all(c==case_sets[0] for c in case_sets)
    common_cases=set.intersection(*case_sets)
    output=[]
    for (model,protocol),rows in sorted(panels.items()):
        covered=[(e,s) for e,s in rows if s["reference_covered"]]
        coverage_rows=[(e,{"coverage":s["reference_covered"]}) for e,s in rows]
        output.append({"model_id":model,"protocol":protocol,"expected_repeats":len(rows),
         "observed_repeats":sum(e["record_id"] in by_id for e,_ in rows),
         "semantic_success":_summary(rows,"S"),"success_at_budget":_summary(rows,"V"),
         "efficient_success_covered":_summary(covered,"efficient_success"),
         "reference_coverage":_summary(coverage_rows,"coverage"),
         "point_scores_publishable":all(s["V"] is not None for _,s in rows)})
    return {"status":"METRIC_CORE_REPORT","scope":"ENGINEERING_CALCULATOR_ONLY","formal_ready":False,
            "epsilon":epsilon,"manifest_hash":digest(manifest),"references_hash":digest(references),
            "panels":output,"records":results,"panel_case_sets_equal":comparable,
            "common_reference_case_ids":sorted(common_cases & refs.keys()),
            "notice":"Bounds describe missing evidence, not statistical uncertainty. Formal CIs and matched panels require the full campaign analysis."}
