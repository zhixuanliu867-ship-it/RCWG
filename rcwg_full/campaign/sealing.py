"""Immutable artifact manifests, explicit audit release and offline integrity checks."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from rcwg_full.evidence import digest, read, sha, write, safe_path
import json
import re
import os
import hashlib
import sqlite3


def relative_file(root, name):
    if not isinstance(name, str) or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('MANIFEST_PATH')
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(p in {'..', '.'} for p in path.parts):
        raise ValueError('MANIFEST_PATH')
    reserved={'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}
    if any(p.endswith((' ','.')) or p.split('.')[0].upper() in reserved for p in path.parts):raise ValueError('MANIFEST_PATH')
    target = safe_path(Path(root) / name)
    if not target.is_relative_to(Path(root).absolute()):
        raise ValueError('MANIFEST_PATH')
    return target


def read_manifest(path):
    path = safe_path(path)
    result = json.loads(read(path))
    claimed = result.get('manifest_hash')
    if not isinstance(claimed, str) or claimed != digest({k: v for k, v in result.items() if k != 'manifest_hash'}):
        raise ValueError('MANIFEST_HASH')
    return result


def check_expected(path):
    manifest = read_manifest(path)
    if manifest.get('schema_version') != 'FULL001_EXPECTED_1':
        raise ValueError('EXPECTED_MANIFEST_VERSION')
    root = Path(path).parent
    from collections import Counter
    identities = set(); files = [manifest['primary'], *manifest['diagnostics'].values()]
    for entry in files:
        raw = read(relative_file(root, entry['file']))
        if sha(raw) != entry['sha256'] or raw and not raw.endswith(b'\n'):
            raise ValueError('EXPECTED_FILE_HASH_OR_PARTIAL')
        counts = Counter()
        for line in raw.splitlines():
            row = json.loads(line)
            if row['slot_id'] in identities:
                raise ValueError('DUPLICATE_EXPECTED_SLOT')
            identities.add(row['slot_id']); counts[row['slot_kind']] += 1
        if dict(counts) != entry['counts'] or sum(counts.values()) != entry['total']:
            raise ValueError('EXPECTED_FILE_COUNTS')
    return manifest


def validate_receipt(receipt, *, action, subject_hash, actor_role, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    if (not isinstance(subject_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',subject_hash) or
            type(receipt) is not dict or receipt.get('approved') is not True or receipt.get('action') != action or
            receipt.get('subject_hash') != subject_hash or receipt.get('actor_role') != actor_role or
            not receipt.get('actor_id') or not receipt.get('receipt_id')):
        raise PermissionError('EXACT_RECEIPT_REQUIRED')
    try:
        start = datetime.fromisoformat(receipt['valid_from'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(receipt['valid_until'].replace('Z', '+00:00'))
        if start.tzinfo is None or end.tzinfo is None or not start <= now < end:
            raise ValueError('expiry')
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionError('RECEIPT_TIME_INVALID') from exc
    return digest(receipt)


def seal_package(root, *, expected_slots, observations, mode, source_identity, extra_files=()):
    """Seal already persisted observations; never synthesize absent slot outcomes."""
    root = safe_path(root)
    if mode not in {'ENGINEERING_NATIVE', 'ENGINEERING_REPLAY', 'FORMAL'}:
        raise ValueError('SEAL_MODE')
    expected_ids = [s['slot_id'] for s in expected_slots]
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError('DUPLICATE_EXPECTED_SLOT')
    known = set(expected_ids); observed = set(); attempts = set()
    active = {'RUNNING', 'CLAIMED', 'SENT_UNCONFIRMED', 'NOT_RUN'}
    for row in observations:
        if row['slot_id'] not in known or row['attempt_id'] in attempts or row['mode'] != mode:
            raise ValueError('SEAL_OBSERVATION_IDENTITY')
        if row['status'] in active:
            raise ValueError('CORE_NOT_TERMINAL')
        if row['status']=='UNKNOWN' and row.get('terminal_reconciliation')!={'worker_stopped':True,'request_uncertain':False}:
            raise ValueError('CORE_NOT_TERMINAL')
        observed.add(row['slot_id']); attempts.add(row['attempt_id'])
    if known != observed:
        raise ValueError('CORE_RECORDS_MISSING')
    files = {'expected.json': write(root / 'expected.json', expected_slots),
             'observations.json': write(root / 'observations.json', observations)}
    for name in extra_files:
        if name in files or name in {'sealed-manifest.json', 'audit-release.json'}:
            raise ValueError('SEAL_FILE_COLLISION')
        files[name] = sha(read(relative_file(root, name)))
    manifest = {'schema_version': 'FULL001_SEALED_1', 'mode': mode, 'status': 'SEALED',
                'core_complete': True, 'expected_count': len(known), 'attempt_count': len(attempts),
                'files': files, 'source_identity': source_identity, 'formal_ready': False}
    manifest['manifest_hash'] = digest(manifest)
    write(root / 'sealed-manifest.json', manifest)
    return manifest


def verify_seal(path):
    manifest = read_manifest(path)
    if manifest.get('schema_version') != 'FULL001_SEALED_1' or manifest.get('status') != 'SEALED' or manifest.get('core_complete') is not True:
        raise ValueError('SEALED_COMPLETE_PACKAGE_REQUIRED')
    for name, expected in manifest['files'].items():
        if sha(read(relative_file(Path(path).parent, name))) != expected:
            raise ValueError('SEALED_ARTIFACT_CHANGED:' + name)
    return manifest


def _file_hash(path):
    hasher=hashlib.sha256()
    with safe_path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):hasher.update(chunk)
    return hasher.hexdigest()


def _snapshot_tree(source,target,*,campaign_snapshot=None):
    """Copy private evidence, snapshot SQLite through its API, reject mutation."""
    source=safe_path(source);target=safe_path(target);target.mkdir(parents=True,exist_ok=False,mode=0o700)
    def inventory():
        found={}
        for item in sorted(source.rglob('*')):
            safe_path(item)
            if item.is_dir():continue
            if not item.is_file():raise ValueError('SEAL_REGULAR_FILE_REQUIRED')
            name=item.relative_to(source).as_posix();relative_file(target,name)
            if name.endswith(('-wal','-shm','-journal')):continue
            found[name]=item
        return found
    original=inventory();digests={};databases={}
    for name,item in original.items():
        destination=relative_file(target,name);destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if item.suffix=='.sqlite3':
            own=campaign_snapshot is None or name!='campaign.sqlite3'
            database=sqlite3.connect(item.as_uri()+'?mode=ro',uri=True) if own else campaign_snapshot
            copy=None
            try:
                if own:database.execute('BEGIN')
                tables={row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'requests' in tables and 'status' in {r[1] for r in database.execute('PRAGMA table_info(requests)')}:
                    if database.execute("SELECT 1 FROM requests WHERE status IN ('PREPARED','SENDING','SENT_UNCONFIRMED') LIMIT 1").fetchone():raise ValueError('SERVICE_REQUEST_NOT_RECONCILED')
                if 'reservations' in tables:
                    if database.execute("SELECT 1 FROM reservations WHERE status IN ('RESERVED_BEFORE_IO','SENT_UNCONFIRMED') LIMIT 1").fetchone():raise ValueError('SERVICE_RESERVATION_NOT_RECONCILED')
                # Logical contents are compared after copying; WAL byte layout
                # is not a stable identity for a transactional SQLite snapshot.
                databases[name]=digest(list(database.iterdump()))
                write(destination,b'');copy=sqlite3.connect(destination);database.backup(copy)
                if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLITE_SNAPSHOT_INTEGRITY')
            finally:
                if copy is not None:copy.close()
                if own:database.close()
        else:
            before=_file_hash(item)
            fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            with item.open('rb') as incoming,os.fdopen(fd,'wb') as outgoing:
                for chunk in iter(lambda:incoming.read(1024*1024),b''):outgoing.write(chunk)
                outgoing.flush();os.fsync(outgoing.fileno())
            if _file_hash(destination)!=before:raise ValueError('RUN_CHANGED_DURING_SEAL')
            digests[name]=before
    if set(inventory())!=set(original):raise ValueError('RUN_CHANGED_DURING_SEAL')
    for name,item in original.items():
        if name in databases:
            with sqlite3.connect(item.as_uri()+'?mode=ro',uri=True) as db:
                if digest(list(db.iterdump()))!=databases[name]:raise ValueError('RUN_CHANGED_DURING_SEAL')
        elif _file_hash(item)!=digests[name]:raise ValueError('RUN_CHANGED_DURING_SEAL')
    return [p.relative_to(target.parent).as_posix() for p in target.rglob('*') if p.is_file()]


def seal_run(manifest_path,output):
    """Offline closure of frozen slots, raw attempts, logs and paid request ledgers."""
    from .store import CampaignStore
    from rcwg_full.evidence import exclusive_directory
    manifest_path=safe_path(manifest_path);manifest=check_expected(manifest_path);root=manifest_path.parent
    expected=[]
    for entry in [manifest['primary'],*manifest['diagnostics'].values()]:
        expected.extend(json.loads(line) for line in read(relative_file(root,entry['file'])).splitlines())
    execution=root/'execution';anchor=json.loads(read(execution/'run-anchor.json'))
    if (anchor['manifest_hash']!=manifest['manifest_hash'] or anchor['spec_hash']!=manifest['spec_hash'] or
        anchor['expected_slots_hash']!=digest(expected)):raise ValueError('SEAL_RUN_BINDING')
    store=CampaignStore(execution/'campaign.sqlite3',read_only=True)
    try:
        store.db.execute('BEGIN')
        registered={row['id']:json.loads(row['definition']) for row in store.db.execute('SELECT id,definition FROM slots')}
        if registered!={row['slot_id']:row for row in expected}:raise ValueError('SEAL_SLOT_BINDING')
        observations=store.observations(anchor['mode'])
        out=exclusive_directory(output)
        files=_snapshot_tree(execution,out/'execution',campaign_snapshot=store.db)
        if (root/'service-evidence').exists():files+=_snapshot_tree(root/'service-evidence',out/'service-evidence')
        source_dir=out/'frozen-inputs';source_dir.mkdir(mode=0o700)
        inputs={manifest_path.name,*[entry['file'] for entry in [manifest['primary'],*manifest['diagnostics'].values()]]}
        if (root/'freeze.json').is_file():inputs.add('freeze.json')
        for name in sorted(inputs):
            destination=relative_file(source_dir,name);destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            write(destination,read(relative_file(root,name)));files.append(destination.relative_to(out).as_posix())
        write(out/'evidence-scope.json',{'schema_version':'FULL001_SEAL_SCOPE_1','raw_attempts':True,
          'raw_service_requests':(root/'service-evidence').exists(),'sqlite_snapshots':True,
          'source_data_and_native_build':'EXTERNAL_FROZEN_ARTIFACTS_BY_HASH','visibility':'PRIVATE'})
        files.append('evidence-scope.json')
        return seal_package(out,expected_slots=expected,observations=observations,mode=anchor['mode'],
            source_identity=anchor['source_identity_hash'],extra_files=sorted(files))
    finally:store.close()


def unseal(path, receipt):
    manifest = verify_seal(path)
    receipt_hash = validate_receipt(receipt, action='AUDIT_UNSEAL', subject_hash=manifest['manifest_hash'], actor_role='Auditor')
    release = {'schema_version': 'FULL001_AUDIT_RELEASE_1', 'sealed_manifest_hash': manifest['manifest_hash'],
               'receipt_hash': receipt_hash, 'actor_id': receipt['actor_id'], 'actor_role': 'Auditor',
               'receipt_id': receipt['receipt_id'], 'action': 'AUDIT_UNSEAL', 'formal_ready': False,
               'receipt':receipt,'released_at':datetime.now(timezone.utc).isoformat()}
    release['release_hash']=digest(release)
    write(Path(path).parent / 'audit-release.json', release)
    return release


def authorized_package(path):
    manifest = verify_seal(path)
    release = json.loads(read(Path(path).parent / 'audit-release.json'))
    if (release.get('schema_version') != 'FULL001_AUDIT_RELEASE_1' or release.get('action') != 'AUDIT_UNSEAL' or
            release.get('sealed_manifest_hash') != manifest['manifest_hash'] or release.get('actor_role') != 'Auditor' or
            release.get('release_hash')!=digest({k:v for k,v in release.items() if k!='release_hash'})):
        raise PermissionError('AUDIT_RELEASE_REQUIRED')
    receipt=release.get('receipt',{})
    if digest(receipt)!=release['receipt_hash'] or receipt.get('actor_id')!=release['actor_id'] or receipt.get('receipt_id')!=release['receipt_id']:
        raise PermissionError('AUDIT_RECEIPT_BINDING')
    validate_receipt(receipt,action='AUDIT_UNSEAL',subject_hash=manifest['manifest_hash'],actor_role='Auditor',now=datetime.fromisoformat(release['released_at']))
    return manifest, release
