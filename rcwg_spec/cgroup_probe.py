"""Read-only cgroup v2 diagnostic. Never creates a group or changes limits."""
from pathlib import Path
from .common import ContractError
FILES=("cpu.stat","memory.current","memory.peak","memory.events","memory.stat","io.stat","cpu.pressure","memory.pressure","io.pressure","cpu.max","memory.max","memory.swap.max","cgroup.procs")

def read_snapshot(directory):
    directory=Path(directory)
    fields={}
    for name in FILES:
        path=directory/name
        try:
            if path.is_symlink():raise PermissionError("symbolic files not accepted")
            # Text preserves future kernel keys; units are converted only by named reducers.
            with path.open(encoding="utf8") as handle:
                value=handle.read(1_000_001)
            if len(value)>1_000_000:raise ValueError("cgroup field too large")
            if name=="cgroup.procs":value="process_count="+str(len(value.splitlines()))
            fields[name]={"status":"READ","text":value.strip()}
        except (OSError,UnicodeError,ValueError) as exc:
            fields[name]={"status":"UNAVAILABLE","text":None,"reason":type(exc).__name__}
    return {"scope":"READ_ONLY_CGROUP_PROBE","fields":fields,"formal_isolation_verified":False,"formal_ready":False}

def cpu_delta(before,after):
    def parse(s):
        d={}
        for line in s.splitlines():
            pair=line.split()
            if len(pair)!=2 or pair[0] in d:raise ContractError("INVALID_CPU_STAT","cpu.stat","two fields, unique keys")
            try:v=int(pair[1])
            except ValueError as exc:raise ContractError("INVALID_CPU_STAT","cpu.stat","integer expected") from exc
            if v<0:raise ContractError("INVALID_CPU_STAT","cpu.stat","nonnegative expected")
            d[pair[0]]=v
        return d
    a,b=parse(before),parse(after)
    if "usage_usec" not in a or "usage_usec" not in b:raise ContractError("MISSING_CPU_STAT","cpu.stat","usage_usec unavailable")
    if b["usage_usec"]<a["usage_usec"]:raise ContractError("COUNTER_RESET","cpu.stat","group reset or identity mismatch")
    return (b["usage_usec"]-a["usage_usec"])/1e6
