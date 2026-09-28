"""One append-only USD5 -> USD15 epoch subcap extension under the old root.

Installation is a local delegated policy decision, not a cloud permission grant,
provider settlement, new epoch, reservation refund, or formal admission. The
caller supplies the real user message reference and its text; these bytes are
provenance and do not cryptographically authenticate the human speaker.
"""
import json
from rcwg_full.evidence import canonical, digest, sha
from .dispatch import DispatchGate

REVISION = 'NEXT_LIVE_BUDGET_EXTENSION_1'
NEW_CAP = 15_000_000


def reservation_snapshot(db):
    return db.execute('SELECT id,scope,kind,amount,status,evidence FROM reservations ORDER BY id').fetchall()


def _stored(db):
    found = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='recovery_budget_extensions'").fetchone()
    if not found:
        return None
    row = db.execute('SELECT body,sha256 FROM recovery_budget_extensions WHERE id=1').fetchone()
    if row is None:
        raise PermissionError('BUDGET_EXTENSION_INCOMPLETE')
    value = json.loads(row[0])
    if digest(value) != row[1]:
        raise PermissionError('BUDGET_EXTENSION_CHANGED')
    return value


def effective_recovery_cap(db, epoch):
    old = epoch['maximum_additional_microusd']
    value = _stored(db)
    if value is None:
        return old
    if (value.get('revision') != REVISION or value.get('epoch_sha256') != digest(epoch)
        or value.get('root_sha256') != epoch['root_sha256']
        or value.get('old_cap_microusd') != old or old != 5_000_000
        or type(value.get('new_cap_microusd')) is not int or value['new_cap_microusd'] != NEW_CAP
        or value.get('measurement_profile') != 'SERVICE_ONLY'
        or value.get('manual_signature') is not False
        or value.get('user_text_sha256') != sha(value.get('user_text','').encode('utf8'))):
        raise PermissionError('BUDGET_EXTENSION_BINDING')
    return value['new_cap_microusd']


def install_extension(state, *, user_text, user_message_reference,
                      expected_root_sha256, expected_epoch_sha256,
                      expected_reservations_sha256):
    """Called only after the task owner delegated this prospective subcap change.

    Uses the existing cross-process dispatch lock + DB transaction. Does not
    open a fuse, write a scope, mutate root/epoch, or send/start anything.
    """
    if (not isinstance(user_text,str) or not user_text.strip() or
        not isinstance(user_message_reference,str) or not user_message_reference.strip()):
        raise PermissionError('BUDGET_EXTENSION_USER_MESSAGE_REQUIRED')
    with DispatchGate(state).locked(), state.db() as db:
        db.execute('BEGIN IMMEDIATE')
        from .recovery import active_epoch
        epoch = active_epoch(db)
        if epoch is None or digest(epoch) != expected_epoch_sha256:
            raise PermissionError('BUDGET_EXTENSION_EPOCH_CHANGED')
        if expected_root_sha256 != digest(state.authority) or epoch['root_sha256'] != expected_root_sha256:
            raise PermissionError('BUDGET_EXTENSION_ROOT_CHANGED')
        if epoch['maximum_additional_microusd'] != 5_000_000:
            raise PermissionError('BUDGET_EXTENSION_OLD_CAP')
        existing = _stored(db)
        if existing is not None:
            effective_recovery_cap(db, epoch)
            if existing['user_text_sha256'] != sha(user_text.encode('utf8')) or existing['user_message_reference'] != user_message_reference:
                raise PermissionError('BUDGET_EXTENSION_ALREADY_INSTALLED')
            return existing
        status = db.execute('SELECT status FROM dispatch_control WHERE id=1').fetchone()[0]
        if status != 'OPEN':
            raise PermissionError('BUDGET_EXTENSION_DISPATCH_NOT_QUIESCENT')
        rows = reservation_snapshot(db)
        if digest(rows) != expected_reservations_sha256:
            raise PermissionError('BUDGET_EXTENSION_HISTORY_CHANGED')
        if any(row[4] == 'RESERVED_BEFORE_IO' for row in rows):
            raise PermissionError('BUDGET_EXTENSION_PENDING_RESERVATION')
        unknown = {row[0] for row in rows if row[2] in {'G','E','COUNT'} and row[4] in {'UNKNOWN','SENT_UNCONFIRMED'}}
        if unknown != set(epoch['isolated_request_ids']):
            raise PermissionError('BUDGET_EXTENSION_NEW_UNRESOLVED')
        used = sum(row[3] for row in rows)
        cleanup = int(state.policy['budget']['cleanup_and_billing_lag_reserve']*1_000_000)
        if used >= state.authority['ceiling_microusd']-cleanup:
            raise PermissionError('BUDGET_EXTENSION_ROOT_EXHAUSTED')
        value = {
            'revision': REVISION, 'root_sha256': expected_root_sha256,
            'epoch_sha256': expected_epoch_sha256,
            'old_cap_microusd': 5_000_000, 'new_cap_microusd': NEW_CAP,
            'baseline_reserved_microusd': epoch['baseline_reserved_microusd'],
            'reserved_at_install_microusd': used,
            'prior_reservations_sha256': expected_reservations_sha256,
            'user_message_reference': user_message_reference, 'user_text': user_text,
            'user_text_sha256': sha(user_text.encode('utf8')),
            'authority_kind': 'USER_TASK_DELEGATION', 'generated_by': 'CODEX',
            'manual_signature': False, 'measurement_profile': 'SERVICE_ONLY',
            'root_ceiling_microusd_unchanged': state.authority['ceiling_microusd'],
            'cleanup_reserve_microusd_unchanged': cleanup,
            'old_reservations_released': False, 'scope_limits_unchanged': True,
        }
        db.execute('CREATE TABLE recovery_budget_extensions(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,sha256 TEXT NOT NULL)')
        db.execute('INSERT INTO recovery_budget_extensions VALUES(1,?,?)',(canonical(value).decode(),digest(value)))
        return value
