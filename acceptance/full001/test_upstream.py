"""Hand-authored source examples; no runtime-generated expected labels."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from rcwg_full.data.upstream import qasper, scifact, export_bundle, controlled_graph, validate_cluster_splits
from rcwg_full.data.review import export_review, import_reviews, adjudicate

LICENSE = {'license_text_sha256': None, 'redistribution_policy': 'PENDING_REVIEW',
           'annotation_provenance': 'source_annotations'}


def paper():
    return {'paper-1': {'title': 'Unicode', 'abstract': '',
            'full_text': [{'section_name': 'Results', 'paragraphs': ['🙂患者提高 5 mg。', 'Second evidence.']}],
            'qas': [{'question_id': 'q1', 'question': 'How much?', 'answers': [
                {'answer': {'unanswerable': False, 'yes_no': None, 'extractive_spans': ['5 mg'],
                            'free_form_answer': '', 'evidence': ['🙂患者提高 5 mg。']}},
                {'answer': {'unanswerable': False, 'yes_no': None, 'extractive_spans': [],
                            'free_form_answer': 'Five milligrams', 'evidence': ['Second evidence.']}}]}]}}


class UpstreamTests(unittest.TestCase):
    def test_qasper_multiple_answers_unicode_and_separate_export(self):
        source = paper(); original = copy.deepcopy(source)
        bundle = qasper(source, upstream_revision='source-abc', license_record=LICENSE)
        self.assertEqual(source, original)
        alternatives = bundle['private']['annotations'][0]['acceptable_annotations']
        self.assertEqual([a['answer_type'] for a in alternatives], ['extractive', 'free_form'])
        doc = bundle['public']['documents'][0]
        span = alternatives[0]['evidence'][0]['candidates'][0]
        self.assertEqual(doc['canonical_text'][span['start_cp']:span['end_cp']], '🙂患者提高 5 mg。')
        self.assertEqual(span['end_cp'] - span['start_cp'], 11)
        self.assertNotIn('answers', bundle['public']['questions'][0])
        with tempfile.TemporaryDirectory() as tmp:
            export_bundle(bundle, Path(tmp) / 'bundle')
            self.assertNotIn('Five milligrams', (Path(tmp) / 'bundle/public/source.json').read_text('utf-8'))
            self.assertIn('Five milligrams', (Path(tmp) / 'bundle/private/annotations.json').read_text('utf-8'))

    def test_duplicate_evidence_is_ambiguous(self):
        source = paper()
        source['paper-1']['full_text'][0]['paragraphs'].append('🙂患者提高 5 mg。')
        adapted = qasper(source, upstream_revision='r', license_record=LICENSE)
        item = adapted['private']['annotations'][0]
        self.assertEqual(item['status'], 'PENDING_REVIEW')
        evidence = item['acceptable_annotations'][0]['evidence'][0]
        self.assertEqual(evidence['status'], 'ALIGNMENT_AMBIGUOUS')
        self.assertEqual(len(evidence['candidates']), 2)

    def test_no_answer_and_incomplete_annotation_are_distinct(self):
        source = paper(); qa = source['paper-1']['qas'][0]
        qa['answers'] = [{'answer': {'unanswerable': True, 'evidence': []}}]
        bundle = qasper(source, upstream_revision='r', license_record=LICENSE)
        self.assertEqual(bundle['private']['annotations'][0]['status'], 'SOURCE_LABELS_AVAILABLE')
        qa['answers'] = []
        self.assertEqual(qasper(source, upstream_revision='r', license_record=LICENSE)['private']['annotations'][0]['status'], 'PENDING_REVIEW')

    def test_scifact_sentence_coordinates_and_unannotated_candidate(self):
        corpus = [{'doc_id': 11, 'title': 'T', 'abstract': ['Repeated.', '🙂Second.', 'Repeated.']}]
        claims = [{'id': 7, 'claim': 'C', 'cited_doc_ids': [11, 12],
                   'evidence': {'11': [{'label': 'CONTRADICT', 'sentences': [2]}]}}]
        bundle = scifact(corpus, claims, upstream_revision='r', license_record=LICENSE)
        row = bundle['private']['annotations'][0]
        self.assertEqual(row['unannotated_candidate_status'], 'unknown')
        self.assertEqual(row['evidence']['11'][0]['status'], 'refuted')
        span = row['evidence']['11'][0]['spans'][0]
        self.assertEqual(span['start_cp'], len('Repeated.\n\n🙂Second.\n\n'))
        self.assertEqual(span['quote'], 'Repeated.')
        self.assertNotIn('evidence', bundle['public']['claims'][0])
        claims[0]['evidence']['11'][0]['sentences'] = [3]
        with self.assertRaisesRegex(ValueError, 'RANGE'):
            scifact(corpus, claims, upstream_revision='r', license_record=LICENSE)

    def test_cluster_overlap_and_graph_label_injection_rejected(self):
        with self.assertRaisesRegex(ValueError, 'LEAKAGE'):
            validate_cluster_splits({'development': ['p1'], 'test': ['p1']})
        result = validate_cluster_splits({'development': ['p1'], 'test': ['p2']})
        self.assertEqual(result['source_clusters'], 2)
        docs = [{'document_id': 'a'}, {'document_id': 'b'}]
        edge = dict(edge_id='e', src='a', dst='b', type='controlled', time=1, weight=1)
        graph = controlled_graph(docs, [edge], revision='v1', rule='public_order_adjacency')
        self.assertFalse(graph['is_real_literature_relation'])
        with self.assertRaisesRegex(ValueError, 'PUBLIC_FIELDS'):
            controlled_graph(docs, [dict(edge, gold='supported')], revision='v1', rule='r')


class ReviewTests(unittest.TestCase):
    def test_blind_export_complete_import_and_independent_adjudication(self):
        items = [{'item_id': 'x', 'question': 'Q', 'source': {'text': 'Source'}, 'contract': {'type': 'bool'}, 'gold': True}]
        with tempfile.TemporaryDirectory() as tmp:
            manifest = export_review(items, ['alice', 'bob'], Path(tmp) / 'blind')
            packages = [json.loads((Path(tmp) / 'blind' / f'reviewer-{i}.json').read_text('utf-8')) for i in [1, 2]]
            self.assertNotIn('gold', packages[0]['items'][0])
            self.assertNotIn('bob', json.dumps(packages[0]))
        def record(label):
            return dict(item_id='x', label=label, reason='Sentence reviewed', source='source-1', timestamp='2026-09-22T08:00:00Z')
        submissions = [{'reviewer_id': reviewer, 'items_hash': manifest['items_hash'], 'records': [record(label)]}
                       for reviewer, label in [('alice', True), ('bob', False)]]
        imported = import_reviews(manifest, submissions)
        self.assertEqual(imported['items'][0]['status'], 'DISAGREEMENT')
        with self.assertRaisesRegex(ValueError, 'THIRD_PERSON'):
            adjudicate(imported, [record(True)], 'alice')
        resolved = adjudicate(imported, [record(True)], 'carol')
        self.assertEqual(resolved['changes'][0]['old_labels'], [True, False])
        self.assertFalse(resolved['formal_approved'])
        submissions[1]['records'] = []
        with self.assertRaisesRegex(ValueError, 'INCOMPLETE'):
            import_reviews(manifest, submissions)

    def test_same_reviewer_and_tampered_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'DISTINCT'):
                export_review([], ['alice', 'alice'], Path(tmp) / 'blind')
        manifest = dict(reviewers=['a', 'b'], items_hash='original', item_ids=[])
        with self.assertRaisesRegex(ValueError, 'SOURCE_MISMATCH'):
            import_reviews(manifest, [{'reviewer_id': r, 'items_hash': 'tampered', 'records': []} for r in ['a', 'b']])
