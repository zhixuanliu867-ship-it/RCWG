"""Generate all planned identities before observations; no dispatch or APIs."""
from itertools import product
from pathlib import Path
from collections import Counter
import json
import hashlib
import os
from rcwg_full.evidence import ROOT,canonical,digest,write,exclusive_directory


def task_grid(split='test'):
    templates=json.loads((ROOT/'specs/full001/templates.json').read_text('utf-8'))['templates']
    for template in templates:
        if template['split']!=split:continue
        for base,condition in product(range(5),['C0','C1','C2','C3']):
            yield {'task_id':f"{template['template_id']}-b{base}-{condition}",'template_id':template['template_id'],
                'family':template['family'],'base_id':base,'condition':condition,'stratum':template['stratum']}


def primary_slots(spec):
    for task,model,protocol,trial in product(task_grid(),spec['generator_slots'],spec['generation_protocols'],spec['generation_attempt_labels']):
        base={**task,'experiment_id':'E1','generator':model,'protocol':protocol,'trial_label':trial,
            'ledger_role':'PRIMARY','plan_source':'GENERATED','status':'NOT_RUN'}
        generation_id=digest({**base,'slot_kind':'generation'})
        yield {'slot_id':generation_id,'slot_kind':'generation','generation_stage':'P0_PHYSICAL' if protocol=='P0' else 'P1_LOGICAL_THEN_PHYSICAL',
            'execution_repeat':None,'expected_dependencies':[],**base}
        for repeat in range(3 if task['family'] in ['F1','F2','F3','F4'] else 2):
            row={**base,'slot_kind':'execution','generation_slot_id':generation_id,'execution_repeat':repeat,
                'generation_stage':None,'expected_dependencies':[generation_id]}
            yield {'slot_id':digest(row),**row}


def selected_tasks(experiment,seed='FULL001-DIAGNOSTIC-SELECTION-1'):
    tasks=list(task_grid());by_template={}
    for row in tasks:by_template.setdefault(row['template_id'],[]).append(row)
    selected=[]
    def ordered(rows):return sorted(rows,key=lambda r:digest({'seed':seed,'experiment':experiment,'task_id':r['task_id']}))
    if experiment in {'E3','E4'}:
        for index,(template,rows) in enumerate(sorted(by_template.items())):
            if experiment=='E4' and rows[0]['family'] not in {'F5','F6'}:continue
            for c in range(4):
                n=(1+(c==index%4)) if experiment=='E3' else (2+(c in {index%4,(index+1)%4}))
                selected.extend(ordered([r for r in rows if r['condition']==f'C{c}'])[:n])
    elif experiment=='E7':
        for family in ['F5','F6']:
            templates=sorted(t for t,rows in by_template.items() if rows[0]['family']==family)
            for i,t in enumerate(templates):selected.extend(ordered(by_template[t])[:8 if i<4 else 7])
    else:raise ValueError('DIAGNOSTIC_SELECTION_UNKNOWN')
    expected={'E3':240,'E4':160,'E7':120}[experiment]
    if len(selected)!=expected or len({r['task_id'] for r in selected})!=expected:raise RuntimeError('SUBSET_COUNT')
    return selected


def diagnostic_slots(experiment):
    if experiment=='E2':
        tasks=[r for r in task_grid() if r['condition']!='C0'];models=[f'G{i}' for i in range(6)];protocols=['P0','P1'];arms=['Frozen']
    elif experiment=='E3':tasks=selected_tasks('E3');models=['G0','G2','G5'];protocols=['P1'];arms=['L','P','S']
    elif experiment=='E4':tasks=selected_tasks('E4');models=['G2','G5'];protocols=['P1'];arms=['window512','window2048','neighbors1','shared_prefix']
    elif experiment=='E7':tasks=selected_tasks('E7');models=['G2','G5'];protocols=['P0','P1'];arms=['executor_E1']
    else:raise ValueError('DIAGNOSTIC_UNKNOWN')
    from functools import lru_cache
    source_tasks={r['task_id']:r for r in task_grid()}
    def primary_dependency(task,model,protocol,trial):
        source_id=task['task_id'] if experiment!='E2' else task['task_id'].rsplit('-',1)[0]+'-C0'
        source=source_tasks[source_id]
        base={**source,'experiment_id':'E1','generator':model,'protocol':protocol,'trial_label':trial,
              'ledger_role':'PRIMARY','plan_source':'GENERATED','status':'NOT_RUN'}
        return digest({**base,'slot_kind':'generation'})
    for task,model,protocol,trial,arm in product(tasks,models,protocols,[17,29],arms):
        plan={**task,'experiment_id':experiment,'generator':model,'protocol':protocol,'trial_label':trial,'arm':arm,
              'ledger_role':'DIAGNOSTIC','status':'NOT_RUN','plan_source':'C0_FROZEN' if experiment=='E2' else 'E1_DERIVED'}
        plan_id=digest(plan)
        if experiment=='E3' and arm=='L':
            yield {**plan,'slot_id':plan_id,'slot_kind':'generation','generation_stage':'GUIDED_PHYSICAL','guidance_revision':'FULL001_E3_L_GUIDANCE_1','expected_dependencies':[]}
        for repeat in range(3 if task['family'] in ['F1','F2','F3','F4'] else 2):
            dependency=plan_id if experiment=='E3' and arm=='L' else primary_dependency(task,model,protocol,trial)
            row={**plan,'slot_kind':'execution','execution_repeat':repeat,'plan_binding':plan_id,
                 'generation_slot_id':dependency,'expected_dependencies':[dependency]}
            yield {'slot_id':digest(row),**row}


def _write_slots(path, rows):
    h=hashlib.sha256();counts=Counter();identities=set()
    with path.open('xb') as f:
        for row in rows:
            if row['slot_id'] in identities:raise RuntimeError('DUPLICATE_SLOT')
            identities.add(row['slot_id']);counts[row['slot_kind']]+=1
            raw=canonical(row)+b'\n';h.update(raw);f.write(raw)
        f.flush();os.fsync(f.fileno())
    return {'file':path.name,'sha256':h.hexdigest(),'counts':dict(counts),'total':sum(counts.values())}


def materialize_expected(campaign_spec, output, *, include_diagnostics=True):
    spec=campaign_spec
    frozen=json.loads((ROOT/'specs/full001/campaign.json').read_text('utf-8'))
    if spec!=frozen:raise ValueError('CAMPAIGN_REQUIRES_VERSIONED_SPEC')
    out=exclusive_directory(output)
    primary=_write_slots(out/'primary.jsonl',primary_slots(spec))
    if primary['counts']!={'generation':23040,'execution':61440}:raise RuntimeError('PRIMARY_COUNT_MISMATCH')
    manifest={'schema_version':'FULL001_EXPECTED_1','campaign_spec_hash':digest(spec),'profile':'RCWG_FULL001_COMPAT1',
        'spec_hash':json.loads((ROOT/'docs/full001/SPEC_IDENTITY.json').read_text('utf-8'))['spec_hash'],
        'status':'PLANNED_ONLY','formal_ready':False,'execution_authorized':False,'primary':primary,'diagnostics':{},
        'http_request_prediction':{'G_primary_if_all_stages_sent':34560,'E':None,'count':None,'retry':0},
        'unknown_costs':['G_PRICE_SNAPSHOT','SEMANTIC_CALL_COUNTS','COUNT_CALLS','REFERENCE_USAGE','CLOUD','STORAGE'],
        'E5':{'pairs':60,'plans':120,'execution_slots':320,'definitions_status':'PREDECLARED_UNFROZEN'},
        'E6':{'reuse':'E1','strata':['standard','compositional','C1']},
        'E8':{'generation':1440,'G_if_all_stages_sent':2160,'execution_range':[2880,4320],'data_status':'NOT_FROZEN'}}
    if include_diagnostics:
        from .diagnostics import controls,control_slots
        definitions=list(controls())
        manifest['E5']['definitions_sha256']=write(out/'E5-controls.json',definitions)
        manifest['diagnostics']['E5']=_write_slots(out/'E5.jsonl',control_slots())
        for experiment in ['E2','E3','E4','E7']:
            manifest['diagnostics'][experiment]=_write_slots(out/(experiment+'.jsonl'),diagnostic_slots(experiment))
            if experiment!='E2':write(out/(experiment+'-selection.json'),selected_tasks(experiment))
    manifest['manifest_hash']=digest(manifest);write(out/'manifest.json',manifest)
    return manifest


def rebind_frozen(plan, source_binding, target_binding):
    """No compiler rewrite: source hash stays fixed in a separate target binding."""
    if source_binding['condition']!='C0' or target_binding['condition'] not in {'C1','C2','C3'}:raise ValueError('E2_CONDITION')
    for field in ['template_id','base_id','generator','protocol','trial_label']:
        if source_binding[field]!=target_binding[field]:raise ValueError('E2_PAIR_MISMATCH')
    return {'source_plan_hash':digest(plan),'source_binding':source_binding,'target_binding':target_binding,
        'plan_unchanged':True,'experiment_id':'E2','arm':'Frozen'}
