"""Offline SPEC acceptance entry points. WorkIR compilation is a later checkpoint."""
import argparse
import json
from pathlib import Path
from .common import load,write_new,ContractError,keys
from .task_input import validate_task
from .metrology import score_manifest
from .cgroup_probe import read_snapshot
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("check")
    a=sub.add_parser("validate-task");a.add_argument("input")
    a=sub.add_parser("score");a.add_argument("input");a.add_argument("--output",required=True)
    a=sub.add_parser("demo");a.add_argument("--output",required=True)
    a=sub.add_parser("cgroup-probe");a.add_argument("directory");a.add_argument("--output",required=True)
    args=p.parse_args()
    try:
        if args.command=="check":
            from rcwg_boot.checks import check
            old=check();contracts=load(ROOT/"specs/spec001a/operator_contracts.json")
            original=load(ROOT/"specs/reference_v1_0/catalogs/operators.json")
            if [x["operator"] for x in contracts]!=[x["operator"] for x in original]:raise ContractError("REGISTRY_IDS","operators","original order/IDs must be preserved")
            if any(x["implementation_status"]!="NOT_IMPLEMENTED" for x in contracts):raise ContractError("STATUS_OVERCLAIM","operators","SPEC-001A does not implement runtime kernels")
            task=validate_task(load(ROOT/"specs/reference_v1_0/examples/task_input.json"))
            report={"status":"SPEC001A_CORE_PASS","reference_files_verified":old["reference_files_verified"],"operator_designs":len(contracts),"task_profile":task["profile"],"full_workir_validator":"NEXT_CHECKPOINT","formal_ready":False}
        elif args.command=="validate-task":report=validate_task(load(args.input))
        elif args.command=="cgroup-probe":report=read_snapshot(args.directory)
        else:
            data=load(ROOT/"specs/spec001a/examples/synthetic_ledger.json" if args.command=="demo" else args.input)
            keys(data,{"manifest","observations","references","fixture_scope"},set(),"$")
            if data["fixture_scope"]!="ENGINEERING_ONLY":
                raise ContractError("ENGINEERING_SCOPE","fixture_scope","this calculator entry point accepts ENGINEERING_ONLY fixtures")
            report=score_manifest(data["manifest"],data["observations"],data["references"])
        if getattr(args,"output",None):write_new(args.output,report)
        print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except (ContractError,OSError,ValueError) as exc:
        detail={"status":"SPEC_ERROR","code":getattr(exc,"code",type(exc).__name__),"path":getattr(exc,"path",None),"formal_ready":False}
        print(json.dumps(detail,ensure_ascii=False));return 2
if __name__=="__main__":raise SystemExit(main())
