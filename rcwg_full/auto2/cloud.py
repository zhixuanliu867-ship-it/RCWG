"""Finite leases with platform-side deadline and guest idle watchdog."""
from rcwg_full.evidence import digest


def validate_lease(lease,policy):
    limits=policy['infrastructure']
    for field,limit in [('vcpu',limits['max_vcpu']),('ram_gib',limits['max_ram_gib']),('disk_gib',limits['max_managed_disk_gib']),('hours',limits['resource_lease_hours'])]:
        if type(lease.get(field)) is not int or not 0<lease[field]<=limit:raise PermissionError('LEASE_RESOURCE_BOUND')
    if lease.get('gpu_count')!=0 or lease.get('simultaneous_vms')!=1:raise PermissionError('LEASE_INSTANCE_BOUND')
    if lease.get('platform_termination_action')!='STOP' or not lease.get('max_run_duration'):
        raise PermissionError('PLATFORM_AUTOSTOP_REQUIRED_BEFORE_CREATE')
    if lease['max_run_duration']!=f"{lease['hours']}h" or lease.get('idle_minutes')!=15:
        raise PermissionError('LEASE_WATCHDOG_BOUND')
    if lease.get('labels',{}).get('task_id')!='rcwg-full-001' or not lease['labels'].get('run_id'):
        raise PermissionError('LEASE_OWNERSHIP_LABELS')
    if not lease.get('startup_script_sha256') or not lease.get('pricing_evidence_sha256'):
        raise PermissionError('LEASE_EVIDENCE_REQUIRED')
    return digest(lease)


def owned_for_cleanup(resource,lease):
    if resource.get('id')!=lease.get('actual_resource_id') or resource.get('labels')!=lease.get('labels'):
        raise PermissionError('NOT_OWNED_RESOURCE')
    if not lease.get('evidence_persisted_and_verified'):raise PermissionError('PERSIST_EVIDENCE_BEFORE_CLEANUP')
    return True
