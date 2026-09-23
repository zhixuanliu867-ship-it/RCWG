"""Private label verification is separate from the public span-check operator."""
from rcwg_full.evidence import canonical

EVIDENCE_POLICY={'revision':'full001-evidence-codepoint-1','unit':'unicode_codepoint','partial_overlap':'intersection_over_unique_cited_units','duplicate_citations':'deduplicate_units','alternatives':'union_for_precision_any_complete_witness_for_coverage','empty_applicable_evidence':'precision_not_applicable_recall_zero','no_applicable_obligations':'not_applicable','unknown_is_refuted':False}


def units(citation):
    if type(citation['start_cp']) is not int or type(citation['end_cp']) is not int or not 0<=citation['start_cp']<citation['end_cp']:raise ValueError('SPAN_RANGE')
    return {(canonical(citation['document_id']),citation['revision'],i) for i in range(citation['start_cp'],citation['end_cp'])}


def evidence_metrics(citations,obligations):
    if not obligations:return {'status':'NOT_APPLICABLE','precision':None,'recall':None,'reason':'NO_APPLICABLE_EVIDENCE','covered':[]}
    observed=set().union(*(units(c) for c in citations)) if citations else set();supported=set();covered=[]
    for obligation in obligations:
        witnesses=[set().union(*(units(c) for c in witness)) for witness in obligation['acceptable_witness_sets']]
        if any(not witness for witness in witnesses):raise ValueError('EMPTY_APPLICABLE_WITNESS')
        for witness in witnesses:supported|=witness
        if any(w<=observed for w in witnesses):covered.append(obligation['id'])
    return {'status':'MEASURED','precision':len(observed&supported)/len(observed) if observed else None,
        'precision_reason':None if observed else 'NO_CITATIONS','recall':len(covered)/len(obligations),'covered':covered,
        'cited_units':len(observed),'supported_cited_units':len(observed&supported)}


def verify_semantics(actual,recipe):
    # Each field obligation carries reviewed alternatives. Unknown remains an explicit value.
    if type(actual) is not dict:return {'status':'FAIL','reason':'SEMANTIC_FORMAT'}
    expected=recipe['fields'];got=actual.get('fields',{});tp=0;fp=0;fn=0;critical=[]
    for name,field in expected.items():
        matched=name in got and any(canonical(got[name])==canonical(v) for v in field['acceptable_values'])
        tp+=int(matched);fn+=int(not matched);fp+=int(name in got and not matched)
        if field.get('critical') and not matched:critical.append(name)
    fp+=len(set(got)-set(expected));denom=2*tp+fp+fn;f1=2*tp/denom if denom else None
    try:metrics=evidence_metrics(actual.get('evidence',[]),recipe.get('evidence_obligations',[]))
    except (ValueError,KeyError,TypeError):return {'status':'FAIL','reason':'EVIDENCE_FORMAT'}
    field_pass=f1 is not None and f1>=recipe.get('field_f1_threshold',.90)
    evidence_pass=metrics['status']=='NOT_APPLICABLE' or (metrics['precision'] is not None and metrics['precision']>=recipe.get('evidence_precision_threshold',.95) and metrics['recall']==1)
    if recipe.get('exact_fields'):field_pass=fp==0 and fn==0
    return {'status':'PASS' if field_pass and evidence_pass and not critical else 'FAIL','field_f1':f1,'field_counts':{'tp':tp,'fp':fp,'fn':fn},'evidence':metrics,'critical_failures':critical,'policy':EVIDENCE_POLICY['revision']}


def information_fidelity(available_units,obligations,*,recoverable_units=()):
    if not obligations:return {'status':'NOT_APPLICABLE','coverage':None,'reason':'NO_APPLICABLE_OBLIGATIONS'}
    available=set(available_units);recoverable=available|set(recoverable_units)
    def covered(pool):return [q['id'] for q in obligations if any(set(w)<=pool for w in q['acceptable_witness_sets'])]
    now=covered(available);later=covered(recoverable)
    return {'status':'OBSERVED','coverage':len(now)/len(obligations),'currently_covered':now,'potentially_recoverable':later,'permanent_loss_claimed':False}
