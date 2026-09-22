"""Blind annotation exchange and explicit third-person adjudication records."""
from copy import deepcopy
from datetime import datetime
from rcwg_full.evidence import digest, exclusive_directory, read, write
import json


def export_review(items, reviewers, output):
    if len(reviewers) != 2 or len(set(reviewers)) != 2 or not all(isinstance(r, str) and r for r in reviewers):
        raise ValueError('TWO_DISTINCT_REVIEWERS_REQUIRED')
    if len({item['item_id'] for item in items}) != len(items):
        raise ValueError('DUPLICATE_REVIEW_ITEM')
    # The whitelist excludes prior answers, source gold and other reviewers' work.
    public = [{'item_id': item['item_id'], 'question': item['question'],
               'source': deepcopy(item['source']), 'contract': deepcopy(item['contract'])} for item in items]
    root = exclusive_directory(output)
    manifest = {'revision': 'FULL001_BLIND_REVIEW_1', 'reviewers': reviewers,
                'items_hash': digest(public), 'item_ids': [i['item_id'] for i in public], 'packages': []}
    for index, reviewer in enumerate(reviewers):
        package = {'reviewer_id': reviewer, 'items_hash': manifest['items_hash'], 'items': public,
                   'status': 'AWAITING_HUMAN_REVIEW'}
        filename = f'reviewer-{index + 1}.json'
        manifest['packages'].append({'file': filename, 'sha256': write(root / filename, package)})
    write(root / 'manifest.json', manifest)
    return manifest


def _record(record, item_ids):
    required = {'item_id', 'label', 'reason', 'source', 'timestamp'}
    if not required <= record.keys() or record['item_id'] not in item_ids or not record['reason'] or not record['source']:
        raise ValueError('REVIEW_RECORD_INCOMPLETE')
    timestamp = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('REVIEW_TIMEZONE_REQUIRED')


def import_reviews(manifest, submissions):
    if len(submissions) != 2 or {s['reviewer_id'] for s in submissions} != set(manifest['reviewers']):
        raise ValueError('REVIEWER_IDENTITY_MISMATCH')
    maps = []
    for submission in submissions:
        if submission['items_hash'] != manifest['items_hash']:
            raise ValueError('REVIEW_SOURCE_MISMATCH')
        mapping = {}
        for record in submission['records']:
            _record(record, manifest['item_ids'])
            if record['item_id'] in mapping:
                raise ValueError('DUPLICATE_REVIEW_RECORD')
            mapping[record['item_id']] = deepcopy(record)
        if set(mapping) != set(manifest['item_ids']):
            raise ValueError('REVIEW_INCOMPLETE')
        maps.append(mapping)
    comparison = []
    for item_id in manifest['item_ids']:
        records = [m[item_id] for m in maps]
        agree = records[0]['label'] == records[1]['label']
        comparison.append({'item_id': item_id, 'status': 'AGREED' if agree else 'DISAGREEMENT',
                           'label': deepcopy(records[0]['label']) if agree else None, 'reviews': records})
    return {'revision': 'FULL001_REVIEW_IMPORT_1', 'manifest_hash': digest(manifest),
            'submissions_hash': digest(submissions), 'reviewer_ids': [s['reviewer_id'] for s in submissions],
            'items': comparison, 'human_identity_authentication': 'REQUIRES_OWNER_IDENTITY_EVIDENCE',
            'formal_approved': False}


def adjudicate(imported, decisions, adjudicator_id):
    if not adjudicator_id or adjudicator_id in imported['reviewer_ids']:
        raise ValueError('INDEPENDENT_THIRD_PERSON_REQUIRED')
    unresolved = {i['item_id'] for i in imported['items'] if i['status'] == 'DISAGREEMENT'}
    if len(decisions) != len(unresolved) or {d['item_id'] for d in decisions} != unresolved:
        raise ValueError('ADJUDICATION_COVERAGE')
    for decision in decisions:
        _record(decision, unresolved)
    by_id = {d['item_id']: d for d in decisions}
    changes = [{'item_id': item['item_id'], 'old_labels': [r['label'] for r in item['reviews']],
                'new_label': deepcopy(by_id[item['item_id']]['label']),
                'decision': deepcopy(by_id[item['item_id']])}
               for item in imported['items'] if item['item_id'] in by_id]
    return {'revision': 'FULL001_ADJUDICATION_1', 'parent_import_hash': digest(imported),
            'adjudicator_id': adjudicator_id, 'changes': changes, 'formal_approved': False}
