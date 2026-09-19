"""Reference reducers for registered physical buffers and application byte events.

Registered-buffer live bytes are NOT worker RAM or process RSS.
Application copy counters are NOT a hardware DRAM traffic counter.
"""
from .common import ContractError,number,keys,text

def live_buffers(buffers,run_end_ns):
    if not isinstance(buffers,list):raise ContractError("ARRAY_REQUIRED","buffers","buffer records must be a list")
    number(run_end_ns,"run_end_ns",integer=True)
    seen=set();events=[];area=0;live_at_end=0
    for b in buffers:
        keys(b,{"buffer_id","bytes","created_ns","released_ns"},set(),"buffers[]")
        text(b["buffer_id"],"buffer_id")
        if b["buffer_id"] in seen:raise ContractError("DUPLICATE_BUFFER","buffer_id","physical allocation IDs are unique; aliases do not allocate")
        seen.add(b["buffer_id"])
        size=number(b["bytes"],"bytes",integer=True);start=number(b["created_ns"],"created_ns",integer=True)
        end=run_end_ns if b["released_ns"] is None else number(b["released_ns"],"released_ns",integer=True)
        if not 0<=start<=end<=run_end_ns:raise ContractError("INVALID_LIFETIME","buffers[]","require 0 <= create <= release <= run_end")
        area+=size*(end-start)
        if start<end:events.extend([(start,1,size),(end,0,-size)])
        if b["released_ns"] is None:live_at_end+=size
    current=peak=0
    for _,_,change in sorted(events):
        current+=change;peak=max(peak,current)
        if current<0:raise ContractError("NEGATIVE_LIVE_BYTES","buffers[]","inconsistent events")
    return {"scope":"REGISTERED_PHYSICAL_BUFFERS_ONLY","buffer_count":len(seen),
      "peak_live_bytes":peak,"live_byte_seconds":area/1e9,"unreleased_bytes_at_end":live_at_end,
      "worker_memory_peak_bytes":None}

def byte_totals(events):
    if not isinstance(events,list):raise ContractError("ARRAY_REQUIRED","byte_events","events must be a list")
    fields=("payload_bytes","read_bytes","copy_bytes","wire_bytes")
    total={k:0 for k in fields};missing={k:0 for k in fields};ids=set()
    for e in events:
        keys(e,{"event_id",*fields},set(),"byte_events[]");text(e["event_id"],"event_id")
        if e["event_id"] in ids:raise ContractError("DUPLICATE_BYTE_EVENT","event_id","do not count both sides of one transfer as two transfers")
        ids.add(e["event_id"])
        for k in fields:
            if e[k] is None:missing[k]+=1
            else:total[k]+=number(e[k],k,integer=True)
    return {"event_count":len(ids),"metrics":{k:{"value":None if missing[k] else total[k],"known_subtotal":total[k],"missing_events":missing[k]} for k in fields},
            "notice":"Byte dimensions overlap and must not be added into a single traffic total."}

def evidence_coverage(obligations,available_units):
    """Private verifier helper over annotated witness IDs, not an LLM truth judge.

Each fact maps to one or more acceptable witness SETS. A complete alternative must
be available. Call separately at each cut; later reacquisition may restore coverage.
"""
    if not isinstance(obligations,dict):raise ContractError("OBLIGATIONS_TYPE","obligations","object required")
    if not isinstance(available_units,list):raise ContractError("ARRAY_REQUIRED","available_units","labelled unit IDs must be a list")
    for u in available_units:text(u,"available_units")
    units=set(available_units)
    if not obligations:return {"covered":0,"required":0,"recall":None,"reason":"NOT_APPLICABLE"}
    covered=[]
    for fact,alternatives in obligations.items():
        text(fact,"fact_id")
        if not isinstance(alternatives,list) or not alternatives:
            raise ContractError("NO_WITNESS_ALTERNATIVES",fact,"at least one labelled alternative required")
        for witness in alternatives:
            if not isinstance(witness,list) or not witness:raise ContractError("EMPTY_WITNESS",fact,"nonempty witness set required")
            for u in witness:text(u,fact)
        if any(set(witness)<=units for witness in alternatives):covered.append(fact)
    return {"covered":len(covered),"required":len(obligations),"recall":len(covered)/len(obligations),"covered_fact_ids":sorted(covered),"reason":None}
