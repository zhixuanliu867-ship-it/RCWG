"""Conservative calibration statuses, retaining every expected attempt."""
from .statistics import overhead
def assess(manifest,reconciled):
    rows={r['run_id']:r for r in reconciled['slots']};checks=[];pairs={}
    for slot in manifest['slots']:
        row=rows[slot['run_id']];r=row.get('result');status='NOT_RUN' if row['status']=='NOT_RUN' else 'INCONCLUSIVE';reasons=[]
        if r:
            m=r.get('measurements') or {};case=slot['case'];w=r.get('worker_report') or {}
            clean=(r.get('cleanup') or {}).get('status')=='REMOVED'
            if r['terminal_status']=='INFRA_FAILURE':status='FAIL';reasons.append('FACILITY_FAILURE')
            elif not clean or m.get('status')!='COUNTERS_OBSERVED':reasons.append('CLEANUP_OR_COUNTERS_INCOMPLETE')
            elif case=='C01':status='PASS' if r['terminal_status']=='COMPLETED' else 'FAIL'
            elif case=='C02':
                cpu=m.get('cpu_usage_usec');independent=w.get('process_cpu_ns')
                if cpu and independent:status='PASS' if abs(cpu*1000/independent-1)<=manifest['tolerances']['cpu_relative_error'] else 'FAIL'
                else:reasons.append('INDEPENDENT_CPU_MISSING')
            elif case=='C03':status='PASS' if 16777216<=(m.get('worker_peak_ram_bytes') or 0)<=33554432 else 'FAIL'
            elif case=='C04':status='PASS' if (m.get('worker_peak_ram_bytes') or 0)>=16777216 and r['terminal_status']=='COMPLETED' else 'FAIL'
            elif case=='C05':reasons.append('OOM_CAUSE_REQUIRES_UNAMBIGUOUS_INDEPENDENT_RECORD')
            elif case=='C06':status='PASS' if r['terminal_status'] in ['CANCELLED','TIMEOUT'] else 'FAIL'
            elif case in ['C09','C10']:status='PASS' if r['terminal_status']=='COMPLETED' and r['verification']=='PASS' else 'FAIL'
            elif case=='C08' and slot['category']!='warmup':
                pairs.setdefault(slot['mode'],{}).setdefault(slot['pair_id'],{})['on_ns' if slot['sampler'] else 'off_ns']=r.get('worker_exec_wall_ns')
        checks.append({'run_id':slot['run_id'],'case':slot['case'],'category':slot['category'],'status':status,'reasons':reasons})
    stats={family:overhead(list(pairs.get(family,{}).values())) for family in ['cpu','stream','fanout','io','short']}
    summary={}
    for i in range(1,11):
        case=f'C{i:02d}';items=[c for c in checks if c['case']==case and c['category']!='warmup'];statuses={c['status'] for c in items}
        status='NOT_RUN' if statuses=={'NOT_RUN'} else ('FAIL' if 'FAIL' in statuses else ('PASS' if statuses=={'PASS'} else 'INCONCLUSIVE'))
        if case=='C08' and statuses!={'NOT_RUN'}:status='PASS' if all(s['status']=='PASS' for s in stats.values()) else ('FAIL' if any(s['status']=='FAIL' for s in stats.values()) else 'INCONCLUSIVE')
        summary[case]={'status':status,'expected':len(items),'observed':sum(c['status']!='NOT_RUN' for c in items)}
    return {'cases':summary,'slots':checks,'overhead':stats,'expected':len(checks),'resource_pairs':324,'resource_slots':648,'formal_ready':False,'budget_within':None}
