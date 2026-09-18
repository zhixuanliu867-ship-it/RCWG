"""Read-only diagnostics. Report paths, usernames, IPs, credentials are excluded."""
from __future__ import annotations
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from .common import now_utc

def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None

def _command_status(args: list[str]) -> str:
    if not shutil.which(args[0]):
        return "NOT_INSTALLED"
    try:
        p = subprocess.run(args, capture_output=True, timeout=5, check=False)
        return "AVAILABLE" if p.returncode == 0 else "UNAVAILABLE_OR_PERMISSION_DENIED"
    except (OSError, subprocess.TimeoutExpired):
        return "UNAVAILABLE_OR_TIMEOUT"

def _cgroup_limits() -> dict:
    # Look at the current process cgroup and its namespace root; do not publish IDs.
    root = Path("/sys/fs/cgroup")
    candidates = [root]
    membership = _read(Path("/proc/self/cgroup")) or ""
    for line in membership.splitlines():
        if line.startswith("0::"):
            p = (root / line[3:].lstrip("/")).resolve()
            if p == root or root in p.parents:
                candidates.insert(0, p)
    result = {"version": "v2" if (root / "cgroup.controllers").exists() else "UNKNOWN_OR_V1"}
    for name in ("cpu.max", "memory.max", "memory.peak", "pids.max"):
        values = [_read(p / name) for p in candidates]
        result[name] = next((v for v in values if v is not None), None)
    result["formal_isolation_verified"] = False
    return result

def collect() -> dict:
    proc_mem = _read(Path("/proc/meminfo")) or ""
    memory = {}
    for line in proc_mem.splitlines():
        label, _, rest = line.partition(":")
        if label in {"MemTotal", "MemAvailable"}:
            memory[label + "_bytes"] = int(rest.split()[0]) * 1024
    release = _read(Path("/etc/os-release")) or ""
    distro = next((s.split("=", 1)[1].strip('"') for s in release.splitlines()
                   if s.startswith("PRETTY_NAME=")), None)
    wsl = "microsoft" in platform.release().lower() or "WSL_INTEROP" in os.environ
    cwd_windows_mount = str(Path.cwd()).startswith("/mnt/") and wsl
    return {
        "ticket": "RCWG-BOOT-001", "collected_at_utc": now_utc(),
        "source": "THIS_PROCESS_ENVIRONMENT", "system": platform.system(),
        "distro": distro, "machine": platform.machine(), "kernel_release": platform.release(),
        "wsl_detected": wsl,
        "python_version": platform.python_version(),
        "python_3_12_target": sys.version_info[:2] == (3, 12),
        "logical_cpu_count": os.cpu_count(),
        "cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "memory": memory, "cgroup": _cgroup_limits(),
        "tools_present": {t: shutil.which(t) is not None for t in ("git", "uv", "docker", "gcloud", "nvidia-smi")},
        "docker_daemon": _command_status(["docker", "info", "--format", "{{.ServerVersion}}"]),
        "gpu_required_for_boot": False,
        "working_directory_on_windows_mount": cwd_windows_mount,
        "network_probed": False, "credentials_probed": False,
        "formal_ready": False,
        "notes": ["Only counts/availability are reported; host identity and environment variables are omitted.",
                  "Memory totals describe this OS/VM; cgroup limits may be smaller.",
                  "Docker availability does not establish benchmark metrology validity."]
    }
