"""Fixed boot fixture: process execution, validation, hashing and persistence only."""
import heapq
import platform
import time
import uuid
from pathlib import Path
from .common import digest, now_utc, write_json

def fixture() -> list[dict]:
    return [{"id": i, "score": (i * 37) % 101, "eligible": i % 3 != 0} for i in range(64)]

def compute(rows: list[dict], k: int = 5) -> list[dict]:
    if not isinstance(k, int) or isinstance(k, bool) or k < 0:
        raise ValueError("k must be a nonnegative integer")
    selected = heapq.nsmallest(k, (r for r in rows if r["eligible"]),
                               key=lambda r: (-r["score"], r["id"]))
    return [{"id": r["id"], "score": r["score"]} for r in selected]

def verify(rows: list[dict], output: list[dict], k: int = 5) -> bool:
    # Independent full-sort path for this fixture, not the research verifier.
    gold = sorted([r for r in rows if r["eligible"]], key=lambda r: (-r["score"], r["id"]))[:k]
    return output == [{"id": r["id"], "score": r["score"]} for r in gold]

def _rss() -> dict:
    try:
        import resource
        n = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        scale = 1 if platform.system() == "Darwin" else 1024
        return {"value_bytes": int(n * scale), "scope": "PROCESS_LIFETIME_HIGH_WATER_MARK",
                "formal_worker_peak": None}
    except (ImportError, OSError):
        return {"value_bytes": None, "scope": "UNAVAILABLE", "formal_worker_peak": None}

def run(output_root: Path) -> tuple[dict, Path]:
    attempt = "boot-" + uuid.uuid4().hex
    rows = fixture()
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    result = compute(rows)
    cpu_ns, wall_ns = time.process_time_ns() - cpu, time.perf_counter_ns() - wall
    ok = verify(rows, result)
    report = {
        "ticket": "RCWG-BOOT-001", "scope": "BOOT_ONLY_NOT_A_BENCHMARK_RESULT",
        "attempt_id": attempt, "created_at_utc": now_utc(),
        "status": "PASS" if ok else "FAIL", "provider": "mock", "api_requests": 0,
        "input_sha256": digest(rows), "output_sha256": digest(result), "result": result,
        "measured_fixture_wall_ns": wall_ns, "measured_fixture_process_cpu_ns": cpu_ns,
        "rss": _rss(), "remote_model_cpu_ns": None, "remote_model_gpu_ns": None,
        "remote_model_vram_bytes": None, "remote_metrics_status": "NOT_OBSERVABLE",
        "formal_result": False, "runtime_python": platform.python_version(),
        "interpretation": "Wall/CPU timing covers fixture compute only; RSS covers process lifetime. No efficiency claim."
    }
    path = output_root / attempt / "report.json"
    write_json(path, report)
    if not ok:
        raise RuntimeError("Fixture validation failed")
    return report, path
