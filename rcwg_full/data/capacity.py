"""Deterministic formal-candidate capacity plan, without allocating task data."""
from copy import deepcopy
import json
from rcwg_full.evidence import ROOT,digest,read

MIB=1024**2
GIB=1024**3


def parameter_table():
    templates=json.loads(read(ROOT/'specs/full001/templates.json'))['templates'];rows=[]
    for template in templates:
        family=template['family'];number=int(template['template_id'][-2:])
        item={'template_id':template['template_id'],'family':family,'split':template['split'],
            'cpu_slots':8,'worker_ram_C0_C1_C3_bytes':8*GIB,'worker_ram_C2_bytes':2*GIB,
            'namespace':'FULL001_FORMAL_CANDIDATE_1_'+template['split'].upper(),
            'seed_disclosure':'PUBLIC_DEVELOPMENT' if template['split']=='development' else 'PRIVATE_UNTIL_AUTHORIZED_RELEASE',
            'c1_axis':template['c1_axis'],'profile':'formal_candidate_v1','formal_frozen':False,
            'builder_status':'FORMAL_SCALE_IMPLEMENTATION_PENDING'}
        if family=='F1':
            item['builder_status']='BOUNDED_BUILDER_AND_SQL_ORACLE_IMPLEMENTED_NATIVE_CAPACITY_UNVERIFIED'
            item.update(c1_axis='selectivity' if number in {2,10} else 'row_count',row_width_candidate_bytes=256,
                        C0={'rows':100000},C1={'rows':100000 if number in {2,10} else 1000000})
            if number in {2,10}:
                item['C0']['eligible_true_ratio']=[3,4];item['C1']['eligible_true_ratio']=[1,8]
        elif family=='F2':
            item['builder_status']='BOUNDED_BUILDER_AND_SQL_ORACLE_IMPLEMENTED_NATIVE_CAPACITY_UNVERIFIED'
            item.update(c1_axis='key_skew' if number==2 else 'selectivity' if number==10 else 'left_row_count',
                        row_width_candidate_bytes=256,C0={'left_rows':100000,'right_rows':10000,'third_rows':1000},
                        C1={'left_rows':100000 if number in {2,10} else 1000000,'right_rows':10000,'third_rows':1000},
                        right_key_multiplicity_max=4,third_key_multiplicity_max=4,
                        join_output_upper_policy='left_rows * 4; chained_join <= left_rows * 16')
            if number==2:item['C0']['left_hot_key_ratio']=[1,100];item['C1']['left_hot_key_ratio']=[4,5]
            if number==10:item['C0']['eligible_true_ratio']=[3,4];item['C1']['eligible_true_ratio']=[1,8]
        elif family=='F3':
            item.update(c1_axis='node_count',row_width_candidate_bytes=256,C0={'nodes':10000},C1={'nodes':100000})
            if number==11:
                item['edge_density']={'kind':'FIXED_DIRECTED_NON_SELF_DENSITY','numerator':1,'denominator':128}
                for condition in ['C0','C1']:
                    n=item[condition]['nodes'];item[condition]['edges_upper']=(n*(n-1)+127)//128
            else:
                item['edge_density']={'kind':'FIXED_AVERAGE_DEGREE','edges_per_node':8}
                for condition in ['C0','C1']:item[condition]['edges_upper']=item[condition]['nodes']*8
        elif family=='F4':
            large=number in {1,2,7,11};size=GIB if large else 256*MIB if number in {9,10} else 64*MIB
            item.update(c1_axis='object_bytes',row_width_candidate_bytes=4096 if large else 32 if number in {3,5,12} else 256,
                        C0={'object_target_bytes':size},C1={'object_target_bytes':min(4*size,4*GIB)},
                        simultaneous_source_objects=2 if number==11 else 1,
                        reference_dynamic_instances='REQUIRES_BOUNDED_FORMAL_REFERENCE_DESIGN' if number in {8,10,12} else 'TO_VALIDATE')
            if large:item.update(worker_ram_C0_C1_C3_bytes=32*GIB,worker_ram_C2_bytes=8*GIB)
        else:
            item.update(C0={'reviewed_source_units':None,'canonical_text_bytes':None},C1={'reviewed_source_units':None,'canonical_text_bytes':None},
                builder_status='UPSTREAM_ADAPTER_PRESENT_FORMAL_TEMPLATE_BINDING_PENDING',
                required_source='QASPER' if family=='F5' else 'SCIFACT_WITH_CONTROLLED_GRAPH',
                source_status='SOURCE_LICENSE_REVIEW_AND_REAL_LABELS_REQUIRED')
        item['parameter_hash']=digest(item);rows.append(item)
    if len(rows)!=72 or len({r['template_id'] for r in rows})!=72:raise ValueError('CAPACITY_TEMPLATE_COUNT')
    return rows


def capacity_plan():
    parameters=parameter_table();instances=[]
    for row in parameters:
        for base in range(5):
            for condition in ['C0','C1','C2','C3']:
                data=deepcopy(row['C1' if condition=='C1' else 'C0']);family=row['family'];width=row.get('row_width_candidate_bytes')
                if family=='F1':logical_estimate=data['rows']*width
                elif family=='F2':logical_estimate=(data['left_rows']+data['right_rows']+data['third_rows'])*width
                elif family=='F3':logical_estimate=(data['nodes']+data['edges_upper'])*width
                elif family=='F4':logical_estimate=data['object_target_bytes']*row['simultaneous_source_objects']
                else:logical_estimate=None
                instances.append({'task_id':f'{row["template_id"]}-b{base}-{condition}','template_id':row['template_id'],
                    'base_id':base,'condition':condition,'split':row['split'],'parameter_hash':row['parameter_hash'],
                    'data_parameters':data,'cpu_slots':row['cpu_slots'],
                    'worker_memory_limit_bytes':row['worker_ram_C2_bytes'] if condition=='C2' else row['worker_ram_C0_C1_C3_bytes'],
                    'layout':'FRAGMENTED_LOGICALLY_IDENTICAL' if condition=='C3' and family in {'F1','F2','F3','F4'} else
                             'REVIEWED_EVIDENCE_LAYOUT_TRANSFORM' if condition=='C3' else 'CANONICAL',
                    'source_payload_bytes_estimate':logical_estimate,'physical_data_bytes':None,'builder_peak_ram_bytes':None,
                    'temporary_disk_bytes':None,'index_bytes':None,'host_capacity_status':'NOT_MEASURED',
                    'formal_reference_feasibility':'NOT_VALIDATED'})
    known=sum(r['source_payload_bytes_estimate'] or 0 for r in instances)
    return {'schema_version':'FULL001_CAPACITY_PLAN_1','profile':'formal_candidate_v1','status':'PLANNED_ONLY',
        'parameter_table':parameters,'parameter_table_hash':digest(parameters),'instances':instances,
        'counts':{'templates':72,'instances':1440,'development':480,'test':960},
        'source_payload_estimate_known_subset_bytes':known,'source_payload_estimate_unknown_instances':sum(r['source_payload_bytes_estimate'] is None for r in instances),
        'estimate_scope':'LOGICAL_SOURCE_PAYLOAD_ONLY; excludes indexes, Arrow/JSON encoding, allocator overhead, replicas, spill, gold and logs',
        'aggregate_disk_upper_bytes':None,'aggregate_builder_ram_upper_bytes':None,
        'host_assessment':'UNKNOWN_UNTIL_FROZEN_BINARY_BUILDERS_AND_CAPACITY_EVIDENCE',
        'implicit_shrink_allowed':False,'profile_revision_required_for_parameter_changes':True,
        'data_allocation_performed':False,'host_load_authorized':False,'formal_frozen':False,'formal_ready':False}
