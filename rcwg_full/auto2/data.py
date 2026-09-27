"""Versioned automatic label provenance. Original annotations are never human re-reviews."""
from copy import deepcopy
from collections import Counter
from pathlib import Path
import json
from rcwg_full.evidence import canonical,digest,read,sha,write,exclusive_directory

CLASSES={'SOURCE_ANNOTATED','PROGRAM_DERIVED','CONTROLLED_TEXT_GRAPH','UNREVIEWED_EXTENSION'}


def source_license_manifest(path,manifest,provenance):
    """Replace the generic generated-data default before sealing natural sources."""
    for entry in manifest['sources']:
        entry['license']={'status':'SOURCE_LICENSE_RECORDED_PRIVATE_API_USE_UNDER_AUTO2',
            'upstream_declaration':deepcopy(provenance['license']),
            'source':provenance['source'],'upstream':provenance['upstream'],
            'upstream_revision':provenance['upstream_revision'],
            'public_redistribution':'IDS_HASHES_AND_CODE_ONLY','new_manual_license_signature':False}
    Path(path).write_bytes(canonical(manifest)+b'\n')


def label_record(kind,source,*,dependencies=(),operation=None,facts=None):
    if kind not in CLASSES:raise ValueError('AUTO2_LABEL_CLASS')
    if kind=='PROGRAM_DERIVED' and (not dependencies or not operation):raise ValueError('DERIVATION_PROOF_REQUIRED')
    if kind=='CONTROLLED_TEXT_GRAPH' and facts is None:raise ValueError('CONTROLLED_FACTS_REQUIRED')
    return {'profile':'RCWG_DATA_AUTO2_1','label_class':kind,'source':source,'dependencies':list(dependencies),
            'operation':operation,'facts_hash':digest(facts) if facts is not None else None,
            'new_human_reviews':0,'automatic_label_admission':kind!='UNREVIEWED_EXTENSION'}


def public_export(value):
    # Explicit schema for model messages: no permissive recursive deletion.
    allowed={'task','documents','source_ids','provenance'}
    if set(value)-allowed:raise ValueError('PUBLIC_PRIVATE_CHANNEL_VIOLATION')
    from rcwg_full.compiler.public_task import validate_public_task
    if 'task' in value:validate_public_task(value['task'])
    forbidden={'gold','answer','acceptable_annotations','original_annotation','annotator_id','expected','facts','private'}
    def inspect(v):
        if isinstance(v,dict):
            if set(v)&forbidden:raise ValueError('PUBLIC_PRIVATE_CHANNEL_VIOLATION')
            for child in v.values():inspect(child)
        elif isinstance(v,list):
            for child in v:inspect(child)
    # Schema field named "answer" is legitimate; inspect only source metadata.
    for key in ['documents','source_ids','provenance']:
        if key in value:inspect(value[key])
    return deepcopy(value)


def source_inventory(bundles):
    """Classify preserved source labels and retain all legal repeated spans."""
    from rcwg_full.data.formal_documents import validate_bundle
    rows=[]
    for bundle in bundles:
        h=validate_bundle(bundle);source=bundle['provenance']['source']
        for a in bundle['private']['annotations']:
            if source=='QASPER':
                alternatives=a['acceptable_annotations']
                valid=bool(alternatives) and all(v['answer_type']!='incomplete' and
                    (v['answer_type']=='unanswerable' or bool(v['evidence'])) and
                    all(e['candidates'] for e in v['evidence']) for v in alternatives)
                ident={'paper_id':a['paper_id'],'question_id':a['question_id']}
                labels=deepcopy(alternatives)
            else:
                valid=a['labels_available'];ident={'claim_id':a['claim_id']};labels=deepcopy(a['evidence'])
            kind='SOURCE_ANNOTATED' if valid else 'UNREVIEWED_EXTENSION'
            rows.append({**ident,'dataset':source,'bundle_hash':h,'label_class':kind,'private_labels':labels,
                'new_human_reviews':0,'unknown_is_negative':False})
    return rows,dict(Counter(r['label_class'] for r in rows))


def build_controlled(template,base,condition,directory):
    """Same template semantics, versioned formal resource bounds, no replay dispatch."""
    import pyarrow as pa
    from rcwg_full.data.document_templates import f5
    from rcwg_full.data.mixed_templates import f6
    from rcwg_full.data.capacity import parameter_table
    from rcwg_full.data.prepare import prepare
    from rcwg_full.runtime.values import arrow_schema
    from rcwg_full.verification.document_oracle import f5_expected
    from rcwg_full.verification.mixed_oracle import f6_expected
    from rcwg_full.compiler import FullCompiler
    from rcwg_full.reference.candidates import candidates
    d=(f5 if template.startswith('F5') else f6)(template,base,condition)
    p=next(r for r in parameter_table() if r['template_id']==template)
    d['task']['resources'].update(cpu_slots=8,worker_memory_limit_bytes=p['worker_ram_C2_bytes'] if condition=='C2' else p['worker_ram_C0_C1_C3_bytes'])
    d['task']['notes']='RCWG_DATA_AUTO2_1 CONTROLLED_TEXT_GRAPH; generated facts, no natural-source or human-review claim.'
    # Distinguish source clusters by template/base without changing codepoint text.
    renames={doc['document_id']:template+'-b'+str(base)+'-'+doc['document_id'] for doc in d['rows']['documents']}
    def rename(v):
        if isinstance(v,dict):return {k:rename(x) for k,x in v.items()}
        if isinstance(v,list):return [rename(x) for x in v]
        if isinstance(v,str):return renames.get(v,v)
        return v
    d=rename(d)
    for node in d['plan']['nodes']:
        if node['operator']=='semantic_extract':node['params']['context_budget']=12288
    values={'dataset:'+alias:(pa.Table.from_pylist(rows,schema=arrow_schema({'kind':'Table','schema':d['schemas'][alias]})) if alias in d['schemas'] else rows) for alias,rows in d['rows'].items()}
    expected=(f5_expected if template.startswith('F5') else f6_expected)(d['expected_args'])
    label=label_record('CONTROLLED_TEXT_GRAPH',{'template':template,'base':base,'seed':d['seed']},facts=d['expected_args'])
    task,manifest,path=prepare(d['task'],values,directory,profile='formal_candidate_v1',layout='fragmented' if condition=='C3' else 'contiguous',provenance=label)
    private=exclusive_directory(path.parent.with_name(path.parent.name+'-private'))
    recipe={'comparison':'source_document_semantics_v1' if template.startswith('F5') else 'source_mixed_semantics_v1',
        'expected':expected,'documents':d['rows']['documents'],'label_provenance':label,'formal_gold_reviewed':False}
    write(private/'private_verifier_recipe.json',recipe);write(private/'controlled_fact_structure.json',d['expected_args'])
    write(private/'label_provenance.json',label)
    proof=FullCompiler().compile(task,d['plan'])
    if proof['status']!='IR_VALIDATED':raise ValueError('AUTO2_CONTROLLED_REFERENCE:'+str(proof['diagnostics']))
    write(path.parent/'reference_plan.json',d['plan']);write(path.parent/'representation_proof.json',proof)
    write(path.parent/'candidate_definitions.json',candidates(task,d['plan']))
    write(path.parent/'condition_invariants.json',{'condition':condition,'logical_hashes':{s['source_id']:s['logical_content_sha256'] for s in manifest['sources']},
        'physical_hashes':{s['source_id']:s['content_sha256'] for s in manifest['sources']},'expected_output_hash':digest(expected),'c3_text_transform':'NONE_PHYSICAL_LAYOUT_ONLY'})
    return {'task':task,'plan':d['plan'],'manifest_path':path,'private_verifier':private/'private_verifier_recipe.json','label':label}


def check_source_answers(actual,recipe):
    """Any complete original answer+witness alternative; no cross-annotation mixing."""
    from rcwg_full.verification.semantic import verify_semantics
    if type(actual) is not list or len(actual)!=1 or type(actual[0]) is not dict:return {'status':'FAIL','reason':'SOURCE_QA_ROW_COUNT'}
    row=actual[0];doc=recipe['document'];fields={k:v for k,v in row.items() if k not in {'evidence','public_span_check'}}
    for cite in row.get('evidence',[]):
        try:
            a,b=cite['start_cp'],cite['end_cp']
            if (cite['document_id'],cite['revision'])!=(doc['document_id'],doc['revision']) or type(a) is not int or type(b) is not int or not 0<=a<b<=len(doc['canonical_text']) or doc['canonical_text'][a:b]!=cite['quote']:
                return {'status':'FAIL','reason':'SOURCE_COORDINATES'}
        except (KeyError,TypeError):return {'status':'FAIL','reason':'SOURCE_COORDINATES'}
    results=[verify_semantics({'fields':fields,'evidence':row.get('evidence',[])},a) for a in recipe['alternatives']]
    return {'status':'PASS' if any(r['status']=='PASS' for r in results) else 'FAIL',
            'comparison':'ORIGINAL_ANNOTATION_ALTERNATIVES','new_human_reviews':0,'alternatives_checked':len(results)}


def check_source_set(actual,recipe):
    if type(actual) is not list:return {'status':'FAIL','reason':'SOURCE_SET_FORMAT'}
    expected=recipe['members']
    keys=[(r.get('query_id'),r.get('paper_id')) for r in actual if isinstance(r,dict)]
    required=[(r['query_id'],r['paper_id']) for r in expected]
    if len(keys)!=len(actual) or len(keys)!=len(set(keys)) or set(keys)!=set(required):
        return {'status':'FAIL','reason':'SOURCE_EXACT_CANDIDATE_SET'}
    checks=[check_source_answers([actual[keys.index((r['query_id'],r['paper_id']))]],r['recipe']) for r in expected]
    return {'status':'PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL','members':checks,
            'comparison':'ANNOTATED_FINITE_DOMAIN_WITH_CONTROLLED_GRAPH','unknown_is_negative':False}


def build_scifact(template,base,condition,directory,bundle,pairs):
    """F6-01 graph filtering over a finite, fully source-annotated candidate domain."""
    if template!='F6-01' or len(pairs)!=5:raise ValueError('SCIFACT_GRAPH_DESIGN')
    import pyarrow as pa
    from rcwg_full.data.formal_documents import validate_bundle
    from rcwg_full.data.document_templates import BASE_FIELDS,EVIDENCE
    from rcwg_full.data.templates import task_shell,Plan,predicate
    from rcwg_full.data.prepare import prepare
    from rcwg_full.runtime.values import arrow_schema
    from rcwg_full.compiler import FullCompiler
    from rcwg_full.reference.candidates import candidates
    source_hash=validate_bundle(bundle);all_docs={d['document_id']:d for d in bundle['public']['documents']}
    annotations={a['claim_id']:a for a in bundle['private']['annotations']}
    selected=pairs if condition=='C1' else pairs[:3]
    docs=[deepcopy(all_docs[p]) for q,p in selected]
    if len({d['document_id'] for d in docs})!=len(docs):raise ValueError('SOURCE_CLUSTER_REUSE')
    rev=docs[0]['revision'];domain='auto2-scifact';n=len(docs)
    ns={'node_id':'Int64'};es={'edge_id':'Int64','src':'Int64','dst':'Int64','type':'Utf8'}
    graph={'domain':domain,'revision':rev,'directed':True,'nodes':[{'node_id':i} for i in range(n+1)],
           'edges':[{'edge_id':i,'src':0,'dst':i+1,'type':'blocked' if i==2 else 'allowed'} for i in range(n)]}
    ms={'node_key':'Int64','document_id':'Utf8','query_id':'Utf8','claim':'Utf8'}
    mapping=[{'node_key':i+1,'document_id':p,'query_id':q,'claim':annotations[q]['original_claim']['claim']} for i,(q,p) in enumerate(selected)]
    fields={**BASE_FIELDS,'status':'Utf8','evidence':EVIDENCE}
    instruction=('Select documents reachable from node 0 in at most 3 outgoing allowed edges, excluding 0. '
        'For each selected document verify its original SciFact claim given in the public mapping table. '
        'Return only supported rows, with query_id equal to claim ID, paper_id and entity_id equal to document ID, '
        'status=supported and verbatim evidence using Unicode codepoint coordinates. Unannotated documents are never negatives.')
    task=task_shell(template,base,condition,instruction,{'id':'result','type':'records','mode':'exact','fields':list(fields),'schema':fields})
    task['resources'].update(cpu_slots=8,worker_memory_limit_bytes=(2 if condition=='C2' else 8)*1024**3)
    task['notes']='RCWG_DATA_AUTO2_1 PROGRAM_DERIVED: original SciFact annotations, explicit controlled_graph; no human re-review.'
    task['datasets']=[{'id':'dataset:graph','kind':'graph','domain':domain,'revision':rev,'schema_source':'AUTO2_PUBLIC_ID_GRAPH_1',
        'node_schema':ns,'edge_schema':es,'node_id_type':'Int64','node_id_field':'node_id','source_field':'src','target_field':'dst','directed':True,
        'stats':{'node_count':n+1,'edge_count':n},'indexes':[]},
        {'id':'dataset:mapping','kind':'table','revision':rev,'schema_source':'SCIFACT_PUBLIC_CLAIMS','schema':ms,'stats':{'row_count':n},'id_field':'document_id','id_domain':domain},
        {'id':'dataset:documents','kind':'document_index','domain':domain,'revision':rev,'schema_source':'SciFact',
         'schema':{'document_id':'Utf8','revision':'Utf8','canonical_text':'Utf8'},'id_type':'Utf8','id_field':'document_id','stats':{'document_count':n},'indexes':[]},
        {'id':'dataset:seeds','kind':'node_set','domain':domain,'revision':rev,'schema_source':'AUTO2_PUBLIC_ID_GRAPH_1','id_type':'Int64','stats':{'item_count':1}}]
    plan=Plan(task['task_id']);plan.value['external_inputs']={'graph':'dataset:graph','seeds':'dataset:seeds','documents':'dataset:documents'}
    maps=plan.scan('mapping',ms)
    view=plan.add('graph_filter','graph_filter','edge_mask',{'graph':'$input.graph'},{'predicate':predicate('type','eq','allowed')},{'graph':'GraphView'})
    reach=plan.add('reachable','graph_reachability','bfs',{'graph':view,'seeds':'$input.seeds'},{'max_hops':3,'direction':'out'},{'nodes':'NodeSet'})
    nodes=plan.project('node_rows',reach,['id'],source_view='ids',representation='table')
    joined=plan.add('map','join','hash',{'left':nodes,'right':maps},{'keys':[{'left':'id','right':'node_key'}],'join_type':'inner','build_side':'right'})
    ids=plan.project('selected_documents',joined,['document_id'])
    text=plan.add('read','read_documents','batched',{'index':'$input.documents','ids':ids},{'fields':['canonical_text'],'batch_size':n,'id_field':'document_id'},{'documents':'DocumentStream'})
    question='Verify the mapped claim for each document. Return query_id, paper_id, entity_id=paper_id, status (supported/refuted/unknown), evidence. Public claims: '+canonical(mapping).decode('utf8')
    extract=plan.add('extract','semantic_extract','fixed_e0',{'documents':text},{'question':question,'field_schema':fields,'context_budget':12288},{'evidence':'EvidenceTable'})
    checked=plan.add('validate','evidence_validate','span_check',{'index':'$input.documents','evidence':extract},{'strict':True},{'evidence':'EvidenceTable'})
    rows=plan.add('stream','stream_read','arrow_batches',{'artifact':checked},{'batch_size':n},{'rows':'Stream[Record]'})
    kept=plan.filter('supported',rows,predicate('status','eq','supported'))
    kept=plan.add('collect','collect','bounded_collect',{'rows':kept},{'limit':n});plan=plan.end(kept)
    members=[];dependencies=[]
    for i,(q,p) in enumerate(selected):
        a=annotations[q];rationales=a['evidence'][p]
        if not a['labels_available'] or not rationales or len({r['status'] for r in rationales})!=1 or any(not r['spans'] for r in rationales):raise ValueError('SCIFACT_DOMAIN_NOT_FULLY_ANNOTATED')
        dependencies.append({'claim_id':q,'document_id':p,'annotation_hash':digest(a)})
        if i==2 or rationales[0]['status']!='supported':continue
        gold={'query_id':q,'paper_id':p,'entity_id':p,'status':'supported'}
        alternatives=[{'fields':{k:{'acceptable_values':[v],'critical':True} for k,v in gold.items()},'exact_fields':True,
            'evidence_obligations':[{'id':'original_rationale','acceptable_witness_sets':[[{k:v for k,v in s.items() if k!='canonical_text_sha256'} for s in r['spans']]]}]} for r in rationales]
        members.append({'query_id':q,'paper_id':p,'recipe':{'document':all_docs[p],'alternatives':alternatives}})
    label=label_record('PROGRAM_DERIVED',{'dataset':'SciFact','bundle_hash':source_hash,'graph_kind':'controlled_graph'},dependencies=dependencies,
                       operation={'rule':'3-hop allowed graph reachability AND original supported label','graph_hash':digest(graph),'unknown_is_negative':False})
    values={'dataset:graph':graph,'dataset:mapping':pa.Table.from_pylist(mapping,schema=arrow_schema({'kind':'Table','schema':ms})),'dataset:documents':docs,'dataset:seeds':[0]}
    task,manifest,path=prepare(task,values,directory,profile='formal_candidate_v1',layout='fragmented' if condition=='C3' else 'contiguous',provenance=label)
    source_license_manifest(path,manifest,bundle['provenance'])
    private=exclusive_directory(path.parent.with_name(path.parent.name+'-private'))
    write(private/'private_verifier_recipe.json',{'comparison':'auto2_source_set_v1','members':members,'label_provenance':label})
    write(private/'derivation_proof.json',{'dependencies':dependencies,'graph':graph,'operation':label['operation'],'expected_members':[(r['query_id'],r['paper_id']) for r in members]})
    proof=FullCompiler().compile(task,plan)
    if proof['status']!='IR_VALIDATED':raise ValueError('SCIFACT_REFERENCE_INVALID:'+str(proof['diagnostics']))
    write(path.parent/'reference_plan.json',plan);write(path.parent/'representation_proof.json',proof)
    write(path.parent/'candidate_definitions.json',candidates(task,plan))
    write(path.parent/'condition_invariants.json',{'condition':condition,'physical_hashes':{s['source_id']:s['content_sha256'] for s in manifest['sources']},'c3_text_transform':'NONE_PHYSICAL_LAYOUT_ONLY'})
    return {'task':task,'plan':plan,'manifest_path':path,'private_verifier':private/'private_verifier_recipe.json','label':label}


def build_qasper(template,base,condition,directory,bundle,question_id):
    """F5-01 single-field source QA with every original answer alternative."""
    if template!='F5-01':raise ValueError('SOURCE_TEMPLATE_NOT_IMPLEMENTED')
    from rcwg_full.data.formal_documents import validate_bundle
    from rcwg_full.data.document_templates import BASE_FIELDS,EVIDENCE
    from rcwg_full.data.templates import task_shell,Plan
    from rcwg_full.data.prepare import prepare
    from rcwg_full.runtime.documents import canonical_document
    from rcwg_full.reference.candidates import candidates
    from rcwg_full.compiler import FullCompiler
    source_hash=validate_bundle(bundle)
    q=next(q for q in bundle['public']['questions'] if q['question_id']==question_id)
    doc=deepcopy(next(d for d in bundle['public']['documents'] if d['document_id']==q['paper_id']))
    annotation=next(a for a in bundle['private']['annotations'] if a['question_id']==question_id)
    if condition=='C1':
        doc=canonical_document(doc['document_id'],doc['revision'],doc['title'],
            [{'section_id':s['section_id'],'heading':s['heading'],'text':s['text']} for s in doc['sections']]+
            [{'section_id':'auto2-neutral-layout-annex','heading':'Formatting annex',
              'text':'This formatting annex contains no evidence about the research question. '*80}],source_record_id=doc['source_record_id'],metadata=doc['metadata'])
    fields={**BASE_FIELDS,'answer':'Utf8','evidence':EVIDENCE};domain='auto2-qasper';rev=doc['revision']
    instruction='Answer the original QASPER question using the supplied paper. Return one row with query_id='+q['question_id']+', paper_id='+q['paper_id']+', entity_id='+q['paper_id']+'. The answer field is a string: yes/no for a boolean question; verbatim span(s) joined with ; for extractive answers; a concise answer otherwise. Cite complete source evidence with Unicode codepoint coordinates. Question: '+q['question']
    output={'id':'result','type':'evidence','mode':'evidence_supported','domain':domain,'revision':rev,'fields':list(fields),'schema':fields}
    task=task_shell(template,base,condition,instruction,output)
    task['resources'].update(cpu_slots=8,worker_memory_limit_bytes=(2 if condition=='C2' else 8)*1024**3)
    task['notes']='RCWG_DATA_AUTO2_1 SOURCE_ANNOTATED; source QA, all acceptable source annotations; no new human review.'
    task['datasets']=[{'id':'dataset:documents','kind':'document_index','domain':domain,'revision':rev,'schema_source':'QASPER-v0.3',
        'schema':{'document_id':'Utf8','revision':'Utf8','canonical_text':'Utf8'},'id_type':'Utf8','id_field':'document_id','stats':{'document_count':1},'indexes':[]},
        {'id':'dataset:ids','kind':'id_selection','domain':domain,'revision':rev,'schema_source':'QASPER-v0.3','id_type':'Utf8','ranked':False,'stats':{'item_count':1}}]
    plan=Plan(task['task_id']);plan.value['external_inputs']={'documents':'dataset:documents','ids':'dataset:ids'}
    ref=plan.add('read','read_documents','batched',{'index':'$input.documents','ids':'$input.ids'},{'fields':['canonical_text'],'batch_size':1},{'documents':'DocumentStream'})
    ref=plan.add('extract','semantic_extract','fixed_e0',{'documents':ref},{'question':instruction,'field_schema':fields,'context_budget':12288},{'evidence':'EvidenceTable'})
    ref=plan.add('validate','evidence_validate','span_check',{'index':'$input.documents','evidence':ref},{'strict':True},{'evidence':'EvidenceTable'})
    plan=plan.end(ref)
    alternatives=[]
    for a in annotation['acceptable_annotations']:
        if a['answer_type']=='incomplete' or (a['answer_type']!='unanswerable' and not a['evidence']) or any(not e['candidates'] for e in a['evidence']):
            raise ValueError('UNREVIEWED_SOURCE_QA')
        value=a['value']
        answer='unknown' if a['answer_type']=='unanswerable' else ('yes' if value else 'no') if a['answer_type']=='boolean' else ';'.join(value) if a['answer_type']=='extractive' else value
        expected={'query_id':q['question_id'],'paper_id':q['paper_id'],'entity_id':q['paper_id'],'answer':answer}
        alternatives.append({'fields':{k:{'acceptable_values':[v],'critical':True} for k,v in expected.items()},'exact_fields':True,
            'evidence_obligations':[{'id':str(i),'acceptable_witness_sets':[[{k:v for k,v in c.items() if k!='canonical_text_sha256'}] for c in e['candidates']]} for i,e in enumerate(a['evidence'])]})
    label=label_record('SOURCE_ANNOTATED',{'dataset':'QASPER','question_id':question_id,'paper_id':q['paper_id'],'bundle_hash':source_hash})
    task,manifest,path=prepare(task,{'dataset:documents':[doc],'dataset:ids':[doc['document_id']]},directory,profile='formal_candidate_v1',layout='fragmented' if condition=='C3' else 'contiguous',provenance=label)
    source_license_manifest(path,manifest,bundle['provenance'])
    private=exclusive_directory(path.parent.with_name(path.parent.name+'-private'))
    recipe={'comparison':'auto2_source_answers_v1','document':doc,'alternatives':alternatives,'label_provenance':label}
    write(private/'private_verifier_recipe.json',recipe);write(private/'source_annotation.json',annotation)
    proof=FullCompiler().compile(task,plan)
    if proof['status']!='IR_VALIDATED':raise ValueError('SOURCE_REFERENCE_INVALID:'+str(proof['diagnostics']))
    write(path.parent/'reference_plan.json',plan);write(path.parent/'representation_proof.json',proof)
    write(path.parent/'candidate_definitions.json',candidates(task,plan))
    write(path.parent/'condition_invariants.json',{'condition':condition,'physical_hashes':{s['source_id']:s['content_sha256'] for s in manifest['sources']},
        'c3_text_transform':'NONE_PHYSICAL_LAYOUT_ONLY','annotation_hash':digest(annotation),'source_cluster':q['paper_id']})
    return {'task':task,'plan':plan,'manifest_path':path,'private_verifier':private/'private_verifier_recipe.json','label':label}
