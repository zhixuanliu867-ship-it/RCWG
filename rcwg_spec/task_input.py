"""Executable public TaskInput checks for the legacy tabular development example.

This is the F1 tabular profile, NOT the full six-family TaskInput implementation.
The typed profile and preserved scope prevent accepting unsupported modalities.
"""
from copy import deepcopy
from .common import ContractError, keys, number, text, digest

SCALARS={"int64","float64","bool","utf8","string","date32","timestamp_us"}
TASK_FIELDS={"task_id","instruction","datasets","resources","output_contract","tool_catalog_id"}

def validate_task(task):
    keys(task,TASK_FIELDS,{"notes"},"$")
    for key in ("task_id","instruction","tool_catalog_id"): text(task[key],f"$.{key}")
    if "notes" in task: text(task["notes"],"$.notes")
    if not isinstance(task["datasets"],list) or not task["datasets"]:
        raise ContractError("DATASETS_REQUIRED","$.datasets","nonempty array")
    ids=set()
    for i,d in enumerate(task["datasets"]):
        p=f"$.datasets[{i}]";keys(d,{"id","schema","stats"},set(),p)
        ident=text(d["id"],p+".id")
        if not ident.startswith("dataset:") or ident in ids:
            raise ContractError("INVALID_DATASET_ID",p+".id","unique dataset: identifier required")
        ids.add(ident)
        if not isinstance(d["schema"],dict) or not d["schema"]:
            raise ContractError("SCHEMA_REQUIRED",p+".schema","nonempty field map")
        for field,kind in d["schema"].items():
            text(field,p+".schema")
            if not isinstance(kind,str) or kind not in SCALARS:
                raise ContractError("UNSUPPORTED_TYPE_PROFILE",p+".schema."+field,"F1 tabular scalar types only")
        keys(d["stats"],{"row_count"},{"estimated_row_bytes","eligible_fraction_estimate","estimate_source"},p+".stats")
        number(d["stats"]["row_count"],p+".stats.row_count",integer=True)
        if "estimated_row_bytes" in d["stats"]:number(d["stats"]["estimated_row_bytes"],p+".stats.estimated_row_bytes",integer=True)
        if "eligible_fraction_estimate" in d["stats"]:
            value=number(d["stats"]["eligible_fraction_estimate"],p+".stats.eligible_fraction_estimate")
            if value>1: raise ContractError("INVALID_FRACTION",p+".stats","must be <=1")
            text(d["stats"].get("estimate_source"),p+".stats.estimate_source")
        elif "estimate_source" in d["stats"]:text(d["stats"]["estimate_source"],p+".stats.estimate_source")
    p="$.resources";b=task["resources"]
    keys(b,{"cpu_slots","worker_memory_limit_bytes","wall_timeout_s"},set(),p)
    number(b["cpu_slots"],p+".cpu_slots",positive=True,integer=True)
    if b["cpu_slots"]>8:raise ContractError("RESOURCE_LIMIT",p+".cpu_slots","RCWG 1.0 maximum is 8")
    number(b["worker_memory_limit_bytes"],p+".worker_memory_limit_bytes",positive=True,integer=True)
    number(b["wall_timeout_s"],p+".wall_timeout_s",positive=True)
    p="$.output_contract";c=task["output_contract"]
    keys(c,{"type","fields","k","tie_breaker","mode"},set(),p)
    if c["type"]!="ordered_records" or c["mode"]!="exact":
        raise ContractError("UNSUPPORTED_OUTPUT_PROFILE",p,"implemented profile is F1 exact ordered_records")
    number(c["k"],p+".k",positive=True,integer=True)
    if not isinstance(c["fields"],list) or not c["fields"]:
        raise ContractError("INVALID_FIELDS",p+".fields","nonempty unique string array")
    for f in c["fields"]:text(f,p+".fields")
    if len(set(c["fields"]))!=len(c["fields"]):raise ContractError("INVALID_FIELDS",p+".fields","duplicate field")
    text(c["tie_breaker"],p+".tie_breaker")
    if c["tie_breaker"] not in c["fields"]:raise ContractError("TIE_BREAKER_MISSING",p,"tie-breaker must be emitted")
    return {"status":"TASKINPUT_PROFILE_PASS","profile":"F1_TABULAR_EXACT_0.1","input_hash":digest(task),"formal_ready":False}

def assemble_public(task):
    """Validate a public object; never open a private bundle, database or gold path."""
    validate_task(task)
    result=deepcopy(task)
    return {"task":result,"input_hash":digest(result),"profile":"F1_TABULAR_EXACT_0.1"}
