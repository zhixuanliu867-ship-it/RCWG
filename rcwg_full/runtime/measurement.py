"""One applicability identity and terminal/budget interpretation for all callers."""
import json
import math
import os
import platform
from pathlib import Path
from rcwg_full.evidence import digest, read, sha, source_hashes


def host_identity():
    def fingerprint(path):
        try: return sha(read(Path(path)))
        except OSError: return 'UNAVAILABLE'
    return {'machine_id_sha256': fingerprint('/etc/machine-id'),
            'boot_id_sha256': fingerprint('/proc/sys/kernel/random/boot_id'),
            'kernel': platform.release(), 'architecture': platform.machine(),
            'system': platform.system(), 'uid': os.getuid() if hasattr(os, 'getuid') else 'UNAVAILABLE'}


def runtime_identity(task, build, *, affinity=None):
    manifest = json.loads(read(Path(build) / 'BUILD.json'))
    return {'host': host_identity(), 'source_hash': digest(source_hashes()),
            'build_hash': sha(read(Path(build) / 'BUILD.json')),
            'binaries': {k: v['sha256'] for k, v in manifest['binaries'].items()},
            'dependencies': manifest['dependencies'], 'lock_sha256': manifest['lock_sha256'],
            'python': manifest['python'], 'soabi': manifest['soabi'],
            'cpu_slots': task['resources']['cpu_slots'],
            'affinity': list(affinity) if affinity is not None else
                        sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else 'UNCONTROLLED',
            'thread_environment': {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                                   'MKL_NUM_THREADS': '1', 'ARROW_NUM_THREADS': '1'}}


def measurement_profile(task, build, *, calibration=None, affinity=None):
    identity = runtime_identity(task, build, affinity=affinity)
    profile = {'revision': 'full001-measurement-2', 'event_source_id': 'full001-worker',
               'clock_id': 'monotonic_ns', 'identity': identity, 'identity_hash': digest(identity),
               'host_calibrated': False, 'calibration_hash': 'NOT_PROVIDED',
               'calibration_status': 'NOT_CALIBRATED'}
    if calibration is not None:
        # Explicit private evidence package; a boolean or an old N4 PASS is not
        # applicability to these FULL binaries. The producer is audited separately.
        from rcwg_full.runtime.calibration import validate_calibration
        verified = validate_calibration(calibration, identity)
        profile.update(host_calibrated=True, calibration_hash=verified,
                       calibration_status='APPLICABLE')
    return profile


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def terminal_budget(report, task):
    """Re-derive decisions; never trust a caller-supplied budget/calibrated flag."""
    metrics = report.get('measurements') or {}
    status = report['terminal_status']
    clean = report.get('cleanup_failures') == [] and report.get('process_group_final', {}).get('live') == []
    go = report.get('execution_started') is True and _number(report.get('exec_started_monotonic_ns'))
    observed = report.get('observed_elapsed_ns')
    deadline = report.get('task_deadline_ns')
    elapsed = report.get('exec_elapsed_ns') if status == 'COMPLETED' else None
    task_ns = task['resources']['wall_timeout_s'] * 1e9
    timeout = (status == 'TIMEOUT' and go and clean and _number(observed) and
               (report.get('failure') or {}).get('code') == 'WALL_TIMEOUT' and
               report.get('effective_timeout_ns') == task_ns and
               deadline == report['exec_started_monotonic_ns'] + task_ns and observed >= task_ns)
    isolated = (report.get('launch_ack', {}).get('status') == 'PASS' and
                report.get('enforced_resources') == task['resources'])
    oom = (go and clean and isolated and metrics.get('status') == 'COUNTERS_OBSERVED' and
           _number(metrics.get('oom_kill_delta')) and metrics['oom_kill_delta'] > 0 and
           _number(metrics.get('run_memory_oom_delta')) and metrics['run_memory_oom_delta'] > 0 and
           metrics.get('cleanup', {}).get('status') == 'REMOVED')
    if oom and status in {'INFRA_FAILURE', 'OOM', 'TIMEOUT'}: status = 'OOM'; elapsed = None
    confirmed = bool(oom or timeout)
    profile = report.get('measurement_profile') or {}
    identity = profile.get('identity', {})
    valid = bool(clean and go and isolated and metrics.get('status') == 'COUNTERS_OBSERVED' and
                 profile.get('host_calibrated') is True and profile.get('calibration_status') == 'APPLICABLE' and
                 profile.get('identity_hash') == digest(identity) and
                 profile.get('calibration_hash') not in {None, 'NOT_PROVIDED'} and
                 metrics.get('cleanup', {}).get('status') == 'REMOVED' and
                 report.get('measurement_identity_verified') is True)
    budget = False if confirmed else None
    peak = metrics.get('worker_peak_ram_bytes')
    if valid and status == 'COMPLETED' and _number(elapsed) and _number(peak) and metrics.get('oom_kill_delta') == 0:
        budget = peak <= task['resources']['worker_memory_limit_bytes'] and elapsed <= task_ns
    return {'status': status, 'budget': budget, 'budget_failure_confirmed': confirmed,
            'measurement_valid': valid, 'observed_elapsed_ns': observed, 'exec_elapsed_ns': elapsed,
            'timing_valid': status == 'COMPLETED' and _number(elapsed) and elapsed > 0 and
                            (report.get('mode') != 'FORMAL' or valid),
            'failure_class': 'CONFIRMED_BUDGET' if confirmed else 'CONFIRMED_PLAN' if status in {'MODEL_FAILURE', 'PLAN_INVALID'}
                             else 'INFRASTRUCTURE' if status == 'INFRA_FAILURE' else None}
