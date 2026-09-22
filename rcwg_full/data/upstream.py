"""Source-preserving adapters. Public text and private annotations never share a file."""
from copy import deepcopy
from pathlib import Path
from rcwg_full.evidence import canonical, digest, sha, write, exclusive_directory
from rcwg_full.runtime.documents import canonical_document, validate_document

REVISION = 'FULL001_UPSTREAM_1'
SOURCES = {
    'QASPER': 'https://github.com/allenai/qasper-led-baseline',
    'SciFact': 'https://github.com/allenai/scifact/blob/master/doc/data.md',
}


def provenance(source, revision, raw, license_record):
    if source not in SOURCES or not isinstance(revision, str) or not revision.strip():
        raise ValueError('UPSTREAM_REVISION_REQUIRED')
    required = {'license_text_sha256', 'redistribution_policy', 'annotation_provenance'}
    if not isinstance(license_record, dict) or not required <= license_record.keys():
        raise ValueError('LICENSE_RECORD_REQUIRED')
    return {'source': source, 'upstream': SOURCES[source], 'upstream_revision': revision,
            'source_sha256': sha(raw), 'transform': REVISION, 'license': deepcopy(license_record),
            'formal_frozen': False}


def _text(value):
    if not isinstance(value, str):
        raise ValueError('SOURCE_TEXT_TYPE')
    value.encode('utf-8', errors='strict')
    return value


def _span(doc, start, end):
    return {'document_id': doc['document_id'], 'revision': doc['revision'],
            'canonical_text_sha256': doc['canonical_text_sha256'],
            'start_cp': start, 'end_cp': end, 'quote': doc['canonical_text'][start:end]}


def align_evidence(doc, quote):
    """Exact paragraph match first; ambiguous repeated text is never first-match gold."""
    quote = _text(quote)
    if not quote:
        return {'status': 'PENDING_REVIEW', 'reason': 'EMPTY_EVIDENCE', 'candidates': []}
    candidates = []
    for section in doc['sections']:
        if section['text'] == quote:
            candidates.append(_span(doc, section['body_start_cp'], section['end_cp']))
    if not candidates:
        cursor = 0
        while True:
            cursor = doc['canonical_text'].find(quote, cursor)
            if cursor < 0:
                break
            candidates.append(_span(doc, cursor, cursor + len(quote)))
            cursor += 1
    return {'status': 'ALIGNED' if len(candidates) == 1 else
            'ALIGNMENT_AMBIGUOUS' if candidates else 'PENDING_REVIEW',
            'reason': None if len(candidates) == 1 else 'NON_UNIQUE_OR_MISSING_EXACT_TEXT',
            'candidates': candidates}


def qasper(papers, *, upstream_revision, license_record):
    source = provenance('QASPER', upstream_revision, canonical(papers), license_record)
    documents, questions, annotations = [], [], []
    seen = set()
    for paper_id, paper in papers.items():
        sections = []
        abstract = _text(paper.get('abstract', ''))
        if abstract:
            sections.append({'section_id': 'abstract', 'heading': 'Abstract', 'text': abstract})
        for section_index, section in enumerate(paper['full_text']):
            for paragraph_index, paragraph in enumerate(section['paragraphs']):
                sections.append({'section_id': f's{section_index}-p{paragraph_index}',
                                 'heading': _text(section['section_name']), 'text': _text(paragraph)})
        doc = canonical_document(str(paper_id), upstream_revision, _text(paper['title']), sections,
                                 source_record_id=str(paper_id), metadata={'source': 'QASPER'})
        validate_document(doc)
        documents.append(doc)
        for qa in paper['qas']:
            question_id = str(qa['question_id'])
            identity = (str(paper_id), question_id)
            if identity in seen:
                raise ValueError('DUPLICATE_QUESTION')
            seen.add(identity)
            questions.append({'paper_id': str(paper_id), 'question_id': question_id,
                              'question': _text(qa['question']), 'document_id': doc['document_id'],
                              'revision': upstream_revision, 'source_cluster': str(paper_id)})
            alternatives = []
            for annotation_index, annotation in enumerate(qa.get('answers', [])):
                answer = annotation['answer']
                unanswerable = answer.get('unanswerable', False)
                if type(unanswerable) is not bool:
                    raise ValueError('ANSWER_TYPE')
                yes_no = answer.get('yes_no')
                if yes_no is not None and type(yes_no) is not bool:
                    raise ValueError('ANSWER_TYPE')
                if unanswerable:
                    kind, value = 'unanswerable', None
                elif yes_no is not None:
                    kind, value = 'boolean', yes_no
                elif answer.get('extractive_spans'):
                    kind, value = 'extractive', [_text(t) for t in answer['extractive_spans']]
                elif answer.get('free_form_answer'):
                    kind, value = 'free_form', _text(answer['free_form_answer'])
                else:
                    kind, value = 'incomplete', None
                evidence = [align_evidence(doc, text) for text in answer.get('evidence', [])]
                complete = kind != 'incomplete' and (unanswerable or bool(evidence)) and all(
                    e['status'] == 'ALIGNED' for e in evidence)
                alternatives.append({'annotation_index': annotation_index, 'answer_type': kind,
                                     'value': value, 'evidence': evidence,
                                     'status': 'SOURCE_LABEL_ALIGNED' if complete else 'PENDING_REVIEW',
                                     'original_annotation': deepcopy(annotation)})
            annotations.append({'paper_id': str(paper_id), 'question_id': question_id,
                                'acceptable_annotations': alternatives,
                                'status': 'SOURCE_LABELS_AVAILABLE' if alternatives and all(
                                    a['status'] == 'SOURCE_LABEL_ALIGNED' for a in alternatives) else 'PENDING_REVIEW'})
    return {'public': {'documents': documents, 'questions': questions},
            'private': {'annotations': annotations, 'original_source': deepcopy(papers)}, 'provenance': source}


def scifact(corpus, claims, *, upstream_revision, license_record):
    source = provenance('SciFact', upstream_revision, canonical({'corpus': corpus, 'claims': claims}), license_record)
    documents, lookup, sentence_spans = [], {}, {}
    for row in corpus:
        doc_id = str(row['doc_id'])
        if doc_id in lookup:
            raise ValueError('DUPLICATE_DOCUMENT')
        doc = canonical_document(doc_id, upstream_revision, _text(row['title']), [
            {'section_id': str(i), 'heading': '', 'text': _text(sentence)}
            for i, sentence in enumerate(row['abstract'])], source_record_id=doc_id,
            metadata={'source': 'SciFact', 'structured': row.get('structured')})
        validate_document(doc)
        lookup[doc_id] = doc
        documents.append(doc)
        sentence_spans[doc_id] = [_span(doc, s['body_start_cp'], s['end_cp']) for s in doc['sections']]
    public_claims, annotations, seen = [], [], set()
    for claim in claims:
        claim_id = str(claim['id'])
        if claim_id in seen:
            raise ValueError('DUPLICATE_CLAIM')
        seen.add(claim_id)
        public_claims.append({'claim_id': claim_id, 'claim': _text(claim['claim']),
                              'cited_doc_ids': [str(i) for i in claim.get('cited_doc_ids', [])]})
        evidence = {}
        for doc_id, rationales in claim.get('evidence', {}).items():
            doc_id = str(doc_id)
            if doc_id not in lookup:
                raise ValueError('EVIDENCE_DOCUMENT_MISSING')
            evidence[doc_id] = []
            for rationale in rationales:
                if rationale['label'] not in {'SUPPORT', 'CONTRADICT'}:
                    raise ValueError('SCIFACT_LABEL')
                indices = rationale['sentences']
                if not indices or any(type(i) is not int or i not in range(len(sentence_spans[doc_id])) for i in indices):
                    raise ValueError('SENTENCE_EVIDENCE_RANGE')
                if len(indices) != len(set(indices)):
                    raise ValueError('DUPLICATE_SENTENCE_EVIDENCE')
                evidence[doc_id].append({'status': 'supported' if rationale['label'] == 'SUPPORT' else 'refuted',
                                         'sentence_indices': list(indices),
                                         'spans': [sentence_spans[doc_id][i] for i in indices],
                                         'original_rationale': deepcopy(rationale)})
        annotations.append({'claim_id': claim_id, 'evidence': evidence,
                            'unannotated_candidate_status': 'unknown',
                            'labels_available': 'evidence' in claim, 'original_claim': deepcopy(claim)})
    return {'public': {'documents': documents, 'claims': public_claims},
            'private': {'annotations': annotations, 'original_corpus': deepcopy(corpus)}, 'provenance': source}


def controlled_graph(documents, public_edges, *, revision, rule):
    """Edges must come from an explicit public rule; no labels are accepted here."""
    ids = {d['document_id'] for d in documents}
    if len(ids) != len(documents) or not rule or not revision:
        raise ValueError('CONTROLLED_GRAPH_IDENTITY')
    edges = []
    seen = set()
    for edge in public_edges:
        if set(edge) != {'edge_id', 'src', 'dst', 'type', 'time', 'weight'}:
            raise ValueError('CONTROLLED_GRAPH_PUBLIC_FIELDS')
        if edge['src'] not in ids or edge['dst'] not in ids or edge['edge_id'] in seen:
            raise ValueError('CONTROLLED_GRAPH_ENDPOINT_OR_ID')
        seen.add(edge['edge_id'])
        edges.append(deepcopy(edge))
    return {'kind': 'controlled_graph', 'text_kind': 'real_text', 'revision': revision,
            'nodes': [{'id': i} for i in sorted(ids)], 'edges': edges,
            'edge_provenance': [{'edge_id': e['edge_id'], 'construction_rule': rule,
                                 'public_edge_sha256': digest(e)} for e in edges],
            'is_real_literature_relation': False}


def validate_cluster_splits(split_clusters):
    owners = {}
    for split, clusters in split_clusters.items():
        for cluster in clusters:
            if cluster in owners and owners[cluster] != split:
                raise ValueError('SOURCE_CLUSTER_LEAKAGE')
            owners[cluster] = split
    return {'status': 'PASS', 'source_clusters': len(owners), 'assignment_sha256': digest(owners)}


def export_bundle(bundle, output):
    root = exclusive_directory(output)
    public, private = exclusive_directory(root / 'public'), exclusive_directory(root / 'private')
    manifest = {'revision': REVISION, 'provenance': bundle['provenance'], 'files': {}, 'formal_frozen': False}
    manifest['files']['public/source.json'] = write(public / 'source.json', bundle['public'])
    manifest['files']['private/annotations.json'] = write(private / 'annotations.json', bundle['private'])
    write(root / 'manifest.json', manifest)
    return manifest
