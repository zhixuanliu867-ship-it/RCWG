"""Bind all F5/F6 template contracts to immutable upstream document bundles.

The task design and derived labels are inputs, never inferred from synthetic
sentences. This tool produces executable candidates and blind review packages;
it cannot authenticate reviewers, settle licenses, or freeze a dataset.
"""
from copy import deepcopy
import json
from pathlib import Path
from rcwg_full.evidence import ROOT,read,write,digest,exclusive_directory
from rcwg_full.compiler import FullCompiler
from rcwg_full.runtime.documents import canonical_document,validate_document
from .upstream import qasper,scifact,validate_cluster_splits

REVISION='FULL001_FORMAL_DOCUMENT_BINDING_1'


def contracts():
    return {r['template_id']:r for r in json.loads(read(ROOT/'specs/full001/templates.json'))['templates'] if r['family'] in {'F5','F6'}}


def validate_bundle(bundle):
    """Reapply the published adapter to original records, detecting label leaks."""
    p=bundle['provenance'];private=bundle['private']
    kw={'upstream_revision':p['upstream_revision'],'license_record':p['license']}
    if p['source']=='QASPER':rebuilt=qasper(private['original_source'],**kw)
    elif p['source']=='SciFact':rebuilt=scifact(private['original_corpus'],[r['original_claim'] for r in private['annotations']],**kw)
    else:raise ValueError('FORMAL_UPSTREAM_SOURCE')
    if digest(rebuilt)!=digest(bundle):raise ValueError('FORMAL_UPSTREAM_BUNDLE_CHANGED')
    return digest(bundle)


def section_view(document,section_ids,*,revision):
    """Extract/reorder complete original sections, retaining a reversible map.

    C1 may include additional source context; its semantic neutrality must be
    reviewed. C3 may reorder sections without replacing any original sentence.
    """
    validate_document(document)
    by_id={s['section_id']:s for s in document['sections']}
    if not section_ids or len(section_ids)!=len(set(section_ids)) or any(i not in by_id for i in section_ids):
        raise ValueError('SOURCE_SECTION_SELECTION')
    selected=[by_id[i] for i in section_ids]
    view=canonical_document(document['document_id'],revision,document['title'],
        [{'section_id':s['section_id'],'heading':s['heading'],'text':s['text']} for s in selected],
        source_record_id=document['source_record_id'],metadata={'source_view':REVISION})
    segments=[]
    for before,after in zip(selected,view['sections']):
        for start,end in [('start_cp','body_start_cp'),('body_start_cp','end_cp')]:
            a,b=after[start],after[end];c,d=before[start],before[end]
            if a==b:continue
            if view['canonical_text'][a:b]!=document['canonical_text'][c:d]:raise ValueError('SOURCE_SECTION_MAPPING')
            segments.append({'view_start_cp':a,'view_end_cp':b,'source_start_cp':c,'source_end_cp':d})
    return view,{'source_document_id':document['document_id'],'source_revision':document['revision'],
        'source_text_sha256':document['canonical_text_sha256'],'view_revision':revision,
        'view_text_sha256':view['canonical_text_sha256'],'segments':segments,'section_ids':list(section_ids)}


def remap_citation(citation,original,view,mapping):
    if (citation['document_id'],citation['revision'])!=(original['document_id'],original['revision']):raise ValueError('CITATION_SOURCE_IDENTITY')
    a,b=citation['start_cp'],citation['end_cp']
    if type(a) is not int or type(b) is not int or not 0<=a<b<=len(original['canonical_text']) or original['canonical_text'][a:b]!=citation['quote']:
        raise ValueError('CITATION_SOURCE_RANGE')
    choices=[s for s in mapping['segments'] if s['source_start_cp']<=a<b<=s['source_end_cp']]
    if len(choices)!=1:raise ValueError('CITATION_VIEW_NOT_CONTIGUOUS')
    s=choices[0];start=s['view_start_cp']+a-s['source_start_cp'];end=start+b-a
    if view['canonical_text'][start:end]!=citation['quote']:raise ValueError('CITATION_VIEW_MAPPING')
    return {'document_id':view['document_id'],'revision':view['revision'],'start_cp':start,'end_cp':end,'quote':citation['quote']}


def _citations(value,documents):
    if isinstance(value,dict):
        if {'document_id','revision','start_cp','end_cp','quote'}<=value.keys():
            key=(value['document_id'],value['revision']);text=documents[key]['canonical_text'];a,b=value['start_cp'],value['end_cp']
            if type(a) is not int or type(b) is not int or not 0<=a<b<=len(text) or text[a:b]!=value['quote']:raise ValueError('GOLD_SOURCE_CITATION')
        for child in value.values():_citations(child,documents)
    elif isinstance(value,list):
        for child in value:_citations(child,documents)


def bind_candidate(bundle,design,expected,directory,*,reviewers,profile='formal_candidate_v1'):
    """Materialize a typed public design over authenticated source records.

    bindings maps each source ID to documents/ids from the bundle, or explicit
    public auxiliary values. Each literal carries a public construction rule.
    Public questions name source question/claim IDs; derived fields require
    subsequent human review. No private answer is put in a public task file.
    """
    import pyarrow as pa
    from .prepare import prepare
    from .review import export_review
    from rcwg_full.runtime.values import arrow_schema
    from rcwg_full.runtime.catalog import DataCatalog
    from rcwg_full.reference.candidates import candidates
    source_hash=validate_bundle(bundle);design=deepcopy(design);task=design['task'];plan=design['plan']
    template=design['template_id'];contract=contracts().get(template)
    if contract is None or design['condition'] not in contract['conditions'] or type(design['base_id']) is not int or design['base_id'] not in range(5):raise ValueError('FORMAL_TEMPLATE_IDENTITY')
    if task['task_id']!=f'{template}-b{design["base_id"]}-{design["condition"]}' or plan['task_id']!=task['task_id']:raise ValueError('FORMAL_TASK_BINDING')
    if profile not in {'formal_candidate_v1','engineering_tiny_v1'}:raise ValueError('FORMAL_BINDING_PROFILE')
    if bundle['provenance']['source']!=('QASPER' if template.startswith('F5') else 'SciFact'):raise ValueError('TEMPLATE_UPSTREAM_MISMATCH')
    if design['contract_sha256']!=digest(contract):raise ValueError('TEMPLATE_CONTRACT_CHANGED')
    split=validate_cluster_splits(design['split_clusters'])
    records={d['document_id']:d for d in bundle['public']['documents']};values={};views={};used=set()
    descriptors={s['id']:s for s in task['datasets']}
    if descriptors.keys()!=design['bindings'].keys():raise ValueError('SOURCE_BINDING_COVERAGE')
    for source_id,binding in design['bindings'].items():
        descriptor=descriptors[source_id];kind=descriptor['kind'];mode=binding['mode']
        if mode in {'documents','ids'}:
            ids=binding['record_ids']
            if len(ids)!=len(set(ids)) or not set(ids)<=records.keys():raise ValueError('SOURCE_RECORD_SELECTION')
            used.update(ids)
            if mode=='documents':
                if kind!='document_index':raise ValueError('SOURCE_BINDING_TYPE')
                docs=[]
                for ident in ids:
                    original=records[ident];sections=binding.get('sections',{}).get(ident)
                    if sections is not None:
                        doc,mapping=section_view(original,sections,revision=descriptor['revision']);views[(ident,doc['revision'])]=mapping
                    else:
                        doc=deepcopy(original)
                        if doc['revision']!=descriptor['revision']:raise ValueError('SOURCE_REVISION_MISMATCH')
                    docs.append(doc)
                descriptor['stats']['document_count']=len(docs);values[source_id]=docs
            else:
                if kind!='id_selection':raise ValueError('SOURCE_BINDING_TYPE')
                values[source_id]=list(ids);descriptor['stats']['item_count']=len(ids)
        elif mode=='public_literal':
            if kind=='document_index' or not binding.get('construction_rule'):raise ValueError('PUBLIC_AUXILIARY_PROVENANCE')
            values[source_id]=deepcopy(binding['value'])
            if kind=='graph':
                graph=values[source_id]
                if set(graph)-{'nodes','edges','domain','revision','directed','edge_index'}:raise ValueError('CONTROLLED_GRAPH_PUBLIC_FIELDS')
                for row in graph['nodes']:
                    if set(row)!=set(descriptor['node_schema']):raise ValueError('CONTROLLED_GRAPH_NODE_FIELDS')
                for row in graph['edges']:
                    if set(row)!=set(descriptor['edge_schema']):raise ValueError('CONTROLLED_GRAPH_EDGE_FIELDS')
                descriptor['stats'].update(node_count=len(graph['nodes']),edge_count=len(graph['edges']))
            if kind=='table':descriptor['stats']['row_count']=len(values[source_id])
        else:raise ValueError('SOURCE_BINDING_MODE')
        if kind=='table':values[source_id]=pa.Table.from_pylist(values[source_id],schema=arrow_schema({'kind':'Table','schema':descriptor['schema']}))
    if not used or not used<=set(design['split_clusters'].get(contract['split'],[])):raise ValueError('SOURCE_CLUSTER_SPLIT_BINDING')
    docs=[d for s in task['datasets'] if s['kind']=='document_index' for d in values[s['id']]]
    originals={(d['document_id'],d['revision']):d for d in docs}
    if len(originals)!=len(docs):raise ValueError('DOCUMENT_IDENTITY_DUPLICATED')
    _citations(expected,originals)
    questions=bundle['public']['questions' if template.startswith('F5') else 'claims']
    key='question_id' if template.startswith('F5') else 'claim_id';by_id={q[key]:q for q in questions}
    if not design.get('source_question_ids') or not set(design['source_question_ids'])<=by_id.keys():raise ValueError('SOURCE_QUESTION_BINDING')
    if not isinstance(expected.get('stages'),dict) or 'result' not in expected:raise ValueError('DERIVED_GOLD_RECIPE')
    stage_names={n['id'] for n in plan['nodes'] if n['operator']=='semantic_extract'}
    if not stage_names or stage_names!=expected['stages'].keys():raise ValueError('DERIVED_GOLD_STAGE_COVERAGE')
    if profile=='formal_candidate_v1':
        from .capacity import parameter_table
        params=next(r for r in parameter_table() if r['template_id']==template)
        task['resources'].update(cpu_slots=params['cpu_slots'],worker_memory_limit_bytes=params['worker_ram_C2_bytes'] if design['condition']=='C2' else params['worker_ram_C0_C1_C3_bytes'])
    compiled=FullCompiler().compile(task,plan)
    if compiled['status']!='IR_VALIDATED':raise ValueError('FORMAL_REFERENCE_INVALID:'+json.dumps(compiled['diagnostics']))
    parent=Path(directory);private=parent.with_name(parent.name+'-private')
    if parent.exists() or private.exists():raise FileExistsError('FORMAL_BINDING_OUTPUT_EXISTS')
    private=exclusive_directory(private)
    comparison='source_document_semantics_v1' if template.startswith('F5') else 'source_mixed_semantics_v1'
    recipe={'revision':REVISION,'comparison':comparison,'expected':deepcopy(expected),'documents':docs,
        'upstream_bundle_hash':source_hash,'derived_labels_status':'PENDING_TWO_HUMAN_REVIEWS',
        'formal_gold_reviewed':False,'formal_ready':False}
    verifier=private/'private_verifier_recipe.json';write(verifier,recipe)
    write(private/'source_annotations.json',bundle['private'])
    binding={'revision':REVISION,'template_id':template,'contract_sha256':digest(contract),'source_bundle_sha256':source_hash,
        'public_design_sha256':digest(design),'private_recipe_sha256':digest(recipe),'source_question_ids':design['source_question_ids'],
        'section_maps':[{'document_id':k[0],**v} for k,v in views.items()],
        'source_cluster_check':split,'license':bundle['provenance']['license'],
        'human_label_authentication':'PENDING','condition_semantics_review':'PENDING',
        'reference_confirmation':'PENDING','formal_frozen':False,'formal_ready':False}
    write(private/'binding.json',binding)
    review=export_review([{'item_id':task['task_id'],'question':task['instruction'],
        'source':{'documents':docs,'source_questions':[by_id[i] for i in design['source_question_ids']],
                  'public_inputs':{s:values[s].to_pylist() if isinstance(values[s],pa.Table) else values[s] for s in values if descriptors[s]['kind']!='document_index'}},
        'contract':{'template':contract['contract'],'output':task['output_contract'],'condition':design['condition'],
                    'condition_claims':design.get('condition_claims',{}),'public_design_sha256':digest(design)}}],reviewers,private/'blind-review')
    task,manifest,path=prepare(task,values,parent,profile=profile,
        layout='fragmented' if design['condition']=='C3' else 'contiguous',provenance=bundle['provenance'])
    # The generic writer's generated-fixture license is not applicable to real text.
    for entry in manifest['sources']:entry['license']=deepcopy(bundle['provenance']['license'])
    from rcwg_full.evidence import canonical
    # Writer owns this newly created manifest; replace it before returning/sealing.
    (parent/'data_manifest.json').write_bytes(canonical(manifest)+b'\n')
    audited=DataCatalog(path).bind(task).audit()
    write(parent/'reference_plan.json',plan);write(parent/'candidate_definitions.json',candidates(task,plan))
    proof={'status':'IR_VALIDATED','task_sha256':digest(task),'plan_sha256':digest(plan),'source_audit':audited,
        'template_contract_sha256':digest(contract),'template_semantics':'REQUIRES_REVIEWED_DERIVED_LABELS',
        'formal_reference_feasible':None,'formal_ready':False}
    write(parent/'representation_proof.json',proof)
    write(parent/'condition_invariants.json',{'condition':design['condition'],'claims':design.get('condition_claims',{}),
        'source_logical_hashes':audited,'sibling_comparison':'PENDING_COMPLETE_CONDITION_GROUP',
        'semantic_neutrality':'PENDING_HUMAN_REVIEW','formal_frozen':False})
    write(parent/'build_manifest.json',{'revision':REVISION,'profile':profile,'template_id':template,
        'private_binding_sha256':digest(binding),'review_manifest_sha256':digest(review),
        'compile_status':'IR_VALIDATED','source_integrity':'PASS','native_execution_performed':False,
        'formal_frozen':False,'formal_ready':False})
    return {'task':task,'plan':plan,'manifest':manifest,'manifest_path':path,'private_verifier':verifier,
        'private_directory':private,'proof':proof,'binding':binding}
