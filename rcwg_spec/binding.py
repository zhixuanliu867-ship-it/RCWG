"""Runner-owned metadata/expected-manifest bindings for future EXEC-001 evidence.

Hashes prove content agreement, not authenticity or actual runtime enforcement.
The runner is the trust boundary: it constructs these objects before execution
from registered metadata and actual plan/compiler bytes. Model-generated WorkIR
fields cannot specify or replace a context, an expected record, or a sidecar.
No file/network/service or resource measurement is performed here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from .common import ContractError, canonical, digest
from .identity import comparison_identity, execution_identity, CONTEXT_HASHES, CONTEXT_TEXT
from .ir_structure import _json_value
from .public_task import validate_public_task

HASH = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
COMPONENTS = ("runtime", "cache_policy", "verifier", "metric_spec", "measurement_profile",
              "operator_registry", "source_manifest")
TERMINAL = frozenset({"COMPLETED", "MODEL_FAILURE", "TIMEOUT", "OOM", "INFRA_FAILURE", "UNKNOWN"})
EVENT_TYPES = frozenset({"run_started", "node_ready", "node_started", "node_finished",
                         "artifact_created", "artifact_read", "artifact_released", "run_finished"})
SIDECAR_FIELDS = frozenset({"record_id", "record_role", "comparison_context_hash", "execution_key",
                            "plan_hash", "compiler_hash", "input_hash", "generation_id", "repeat_id",
                            "repeat_role", "events_sha256", "event_count", "terminal_status",
                            "verification", "context_hashes", "manifest_hash"})


def _fail(code, path="", detail="evidence binding rejected"):
    raise ContractError(code, path, detail) from None


def _obj(value, required, optional=(), path=""):
    if type(value) is not dict or not all(type(key) is str for key in value):
        _fail("BINDING_SHAPE", path, "closed object required")
    if set(value) - set(required) - set(optional) or set(required) - set(value):
        _fail("BINDING_SHAPE", path, "required fields missing or unknown fields present")


def _id(value, path):
    if type(value) is not str or not ID.fullmatch(value):
        _fail("BINDING_ID", path, "bounded identifier required")


def _hash(value, path):
    if type(value) is not str or not HASH.fullmatch(value):
        _fail("BINDING_HASH", path, "lowercase SHA256 hex required")


def _json_contract(value):
    _json_value(value)
    todo = [value]
    while todo:
        item = todo.pop()
        if type(item) is int and not -(2**63) <= item < 2**63:
            _fail("BINDING_NUMBER", "", "evidence integers must fit signed 64-bit range")
        if type(item) is dict:
            todo.extend(item.values())
        elif type(item) is list:
            todo.extend(item)


def _complete(value, path):
    """Reject unresolved identities rather than hashing placeholder metadata."""
    _json_contract(value)
    stack = [value]
    while stack:
        item = stack.pop()
        if item is None or (type(item) is str and
                            (not item.strip() or item.strip().upper() in
                             {"UNRESOLVED", "UNKNOWN", "NOT_FROZEN", "TBD"})):
            _fail("CONTEXT_NOT_BOUND", path, "required authoritative metadata unresolved")
        if type(item) is dict:
            stack.extend(item.values())
        elif type(item) is list:
            stack.extend(item)


def _snapshot_object(raw, code):
    if type(raw) is not bytes:
        _fail(code, "", "canonical snapshot bytes required")
    try:
        value = json.loads(raw)
        _json_contract(value)
        if type(value) is not dict or canonical(value) != raw:
            _fail(code, "", "canonical snapshot object required")
        return value
    except (ValueError, UnicodeError, RecursionError, TypeError):
        _fail(code, "", "snapshot is malformed or noncanonical")


@dataclass(frozen=True, slots=True)
class RunnerContext:
    """Immutable canonical snapshot; create only with build_context in a runner."""
    _snapshot: bytes

    def as_dict(self):
        return _snapshot_object(self._snapshot, "CONTEXT_INTEGRITY")

    @property
    def comparison_context_hash(self):
        return _context_snapshot(self)["identity"]["comparison_context_hash"]


@dataclass(frozen=True, slots=True)
class ExpectedManifest:
    """Pre-execution denominator/role snapshot; output access returns copies."""
    _snapshot: bytes

    def as_dict(self):
        return _snapshot_object(self._snapshot, "EXPECTED_MANIFEST")

    @property
    def manifest_hash(self):
        _manifest(self)
        return hashlib.sha256(self._snapshot).hexdigest()


def build_context(task: dict, *, condition_id: str, data_manifest: list[dict],
                  runtime: dict, cache_policy: dict, verifier: dict, metric_spec: dict,
                  measurement_profile: dict, operator_registry: dict,
                  source_manifest: dict) -> RunnerContext:
    """Bind supplied runner metadata to actual validated public source identities.

    data_manifest entries are exactly id/revision/content_sha256/schema_hash.
    Their IDs, revisions, content and schema must match the public data registry.
    Each component is a nonempty JSON object with a nonempty revision. Its full
    canonical content is hashed; a caller cannot substitute a claimed hash.
    measurement_profile additionally declares event_source_id and clock_id.
    """
    checked = validate_public_task(task)
    _id(condition_id, "/condition_id")
    if type(data_manifest) is not list or not data_manifest:
        _fail("DATA_MANIFEST", "/data_manifest", "nonempty authoritative data manifest required")
    public_sources = {item["id"]: item for item in checked["source_manifest"]}
    found = set()
    for entry in data_manifest:
        _obj(entry, {"id", "revision", "content_sha256", "schema_hash"}, path="/data_manifest")
        _complete(entry, "/data_manifest")
        ident = entry["id"]
        if type(ident) is not str or ident in found or ident not in public_sources:
            _fail("DATA_MANIFEST", "/data_manifest", "manifest source identities differ")
        found.add(ident)
        public = public_sources[ident]
        _hash(entry["content_sha256"], "/data_manifest/content_sha256")
        _hash(entry["schema_hash"], "/data_manifest/schema_hash")
        if public.get("revision") is None or public.get("data_sha256") is None:
            _fail("CONTEXT_NOT_BOUND", "/data_manifest", "public source revision and content evidence required")
        if (entry["revision"] != public["revision"] or entry["content_sha256"] != public["data_sha256"]
                or entry["schema_hash"] != public["schema_hash"]):
            _fail("DATA_MANIFEST_MISMATCH", "/data_manifest", "actual and public source identities differ")
    if found != set(public_sources):
        _fail("DATA_MANIFEST", "/data_manifest", "expected public sources missing")
    components = {"runtime": runtime, "cache_policy": cache_policy, "verifier": verifier,
                  "metric_spec": metric_spec, "measurement_profile": measurement_profile,
                  "operator_registry": operator_registry, "source_manifest": source_manifest}
    for name, value in components.items():
        if type(value) is not dict or not value or "revision" not in value:
            _fail("CONTEXT_NOT_BOUND", "/" + name, "versioned authoritative metadata required")
        _complete(value, "/" + name)
        if type(value["revision"]) is not str:
            _fail("CONTEXT_NOT_BOUND", "/" + name, "metadata revision must be text")
    for field in ("event_source_id", "clock_id"):
        _id(measurement_profile.get(field), "/measurement_profile/" + field)
    if source_manifest.get("public_sources") != checked["source_manifest"]:
        _fail("SOURCE_MANIFEST_MISMATCH", "/source_manifest", "source registry must bind all public source evidence")
    # Canonical source list order is registry identity, not caller enumeration.
    manifest = sorted(data_manifest, key=lambda entry: entry["id"])
    context = {"case_id": checked["normalized_task"]["task_id"], "condition_id": condition_id,
               "data_manifest_hash": digest(manifest),
               "resource_profile_hash": digest(checked["normalized_task"]["resources"]),
               **{name + "_hash": digest(value) for name, value in components.items()}}
    snapshot = {"schema_version": "SPEC001B_BOUND_CONTEXT_0.1", "identity": comparison_identity(context),
                "task_input_hash": checked["task_input_hash"],
                "normalized_input_hash": checked["normalized_input_hash"],
                "authoritative_metadata": {"data_manifest": manifest,
                                           "resource_profile": checked["normalized_task"]["resources"],
                                           **components},
                "formal_ready": False, "runtime_enforcement": "NOT_VERIFIED"}
    return RunnerContext(canonical(snapshot))


def _context_snapshot(context):
    if type(context) is not RunnerContext:
        _fail("RUNNER_CONTEXT_REQUIRED", "", "runner-built immutable context required")
    snapshot = context.as_dict()
    _obj(snapshot, {"schema_version", "identity", "task_input_hash", "normalized_input_hash",
                    "authoritative_metadata", "formal_ready", "runtime_enforcement"})
    if (snapshot["schema_version"] != "SPEC001B_BOUND_CONTEXT_0.1" or snapshot["formal_ready"] is not False
            or snapshot["runtime_enforcement"] != "NOT_VERIFIED"):
        _fail("CONTEXT_INTEGRITY", "", "snapshot version or readiness differs")
    _hash(snapshot["task_input_hash"], "/task_input_hash")
    _hash(snapshot["normalized_input_hash"], "/normalized_input_hash")
    _obj(snapshot["identity"], {"identity_version", "context", "comparison_context_hash"})
    bound = snapshot["identity"]["context"]
    _obj(bound, CONTEXT_HASHES | CONTEXT_TEXT)
    _obj(snapshot["authoritative_metadata"], {"data_manifest", "resource_profile", *COMPONENTS})
    for name, value in snapshot["authoritative_metadata"].items():
        if digest(value) != bound[name + "_hash"]:
            _fail("CONTEXT_INTEGRITY", "", "context content identity mismatch")
    if comparison_identity(bound) != snapshot["identity"]:
        _fail("CONTEXT_INTEGRITY", "", "comparison identity mismatch")
    return snapshot


def freeze_expected(context: RunnerContext, specifications: list[dict]) -> ExpectedManifest:
    """Freeze expected records before execution, hashing actual plan/source bytes.

    Each specification has record_id, record_role (MODEL/REFERENCE), plan (dict),
    compiler_source (nonempty bytes), generation_id, repeat_id and repeat_role.
    The manifest carries model and reference plans independently. Repeats and
    timing confirmations have distinct keys; references need the same context,
    never the same plan hash. This is not the 23,040 generation-attempt matrix.
    """
    snapshot = _context_snapshot(context)
    if type(specifications) is not list or not specifications:
        _fail("EXPECTED_MANIFEST", "", "nonempty expected record specification list required")
    records, ids, execution_keys = [], set(), set()
    for spec in specifications:
        _obj(spec, {"record_id", "record_role", "plan", "compiler_source", "generation_id",
                    "repeat_id", "repeat_role"}, path="/expected")
        for field in ("record_id", "generation_id", "repeat_id"):
            _id(spec[field], "/expected/" + field)
        if spec["record_id"] in ids:
            _fail("EXPECTED_DUPLICATE", "/expected", "duplicate expected record identity")
        if type(spec["record_role"]) is not str or spec["record_role"] not in {"MODEL", "REFERENCE"}:
            _fail("EXPECTED_ROLE", "/expected/record_role", "unknown record role")
        if type(spec["compiler_source"]) is not bytes or not spec["compiler_source"]:
            _fail("COMPILER_SOURCE", "/expected/compiler_source", "actual nonempty compiler source bytes required")
        _json_contract(spec["plan"])
        if type(spec["plan"]) is not dict:
            _fail("PLAN_BINDING", "/expected/plan", "actual plan object required")
        if spec["plan"].get("task_id") != snapshot["identity"]["context"]["case_id"]:
            _fail("PLAN_BINDING", "/expected/plan", "plan case differs from bound task")
        if type(spec["repeat_role"]) is not str or spec["repeat_role"] not in {"PRIMARY_REPEAT", "TIMING_CONFIRMATION"}:
            _fail("EXPECTED_ROLE", "/expected/repeat_role", "unknown repetition role")
        identity = execution_identity(snapshot["identity"]["context"], plan_hash=digest(spec["plan"]),
                                      compiler_hash=hashlib.sha256(spec["compiler_source"]).hexdigest(),
                                      input_hash=snapshot["task_input_hash"], generation_id=spec["generation_id"],
                                      repeat_id=spec["repeat_id"], repeat_role=spec["repeat_role"])
        if identity["execution_key"] in execution_keys:
            _fail("EXPECTED_DUPLICATE", "/expected", "duplicate execution identity across records")
        ids.add(spec["record_id"])
        execution_keys.add(identity["execution_key"])
        records.append({"record_id": spec["record_id"], "record_role": spec["record_role"], **identity})
    return ExpectedManifest(canonical({"schema_version": "SPEC001B_EXPECTED_0.1",
                                       "context": snapshot, "expected_records": records,
                                       "formal_ready": False}))


def _manifest(manifest):
    if type(manifest) is not ExpectedManifest:
        _fail("EXPECTED_MANIFEST_REQUIRED", "", "immutable pre-execution manifest required")
    payload = manifest.as_dict()
    _obj(payload, {"schema_version", "context", "expected_records", "formal_ready"})
    if payload["schema_version"] != "SPEC001B_EXPECTED_0.1" or payload["formal_ready"] is not False:
        _fail("EXPECTED_MANIFEST", "", "manifest version or readiness differs")
    _context_snapshot(RunnerContext(canonical(payload["context"])))
    records = payload["expected_records"]
    if type(records) is not list or not records:
        _fail("EXPECTED_MANIFEST", "", "expected records cannot be empty")
    ids, execution_keys = set(), set()
    for record in records:
        _obj(record, {"record_id", "record_role", "identity_version", "comparison_context_hash", "plan_hash",
                      "compiler_hash", "input_hash", "generation_id", "repeat_id", "repeat_role", "execution_key"})
        for field in ("record_id", "generation_id", "repeat_id"):
            _id(record[field], "/expected/" + field)
        if type(record["record_role"]) is not str or record["record_role"] not in {"MODEL", "REFERENCE"}:
            _fail("EXPECTED_ROLE", "", "unknown record role")
        expected_identity = execution_identity(payload["context"]["identity"]["context"],
            plan_hash=record["plan_hash"], compiler_hash=record["compiler_hash"], input_hash=record["input_hash"],
            generation_id=record["generation_id"], repeat_id=record["repeat_id"], repeat_role=record["repeat_role"])
        if (any(record[key] != value for key, value in expected_identity.items())
                or record["input_hash"] != payload["context"]["task_input_hash"]):
            _fail("EXPECTED_MANIFEST", "", "expected execution identity differs from bound context")
        if record["record_id"] in ids or record["execution_key"] in execution_keys:
            _fail("EXPECTED_DUPLICATE", "", "duplicate expected record or execution identity")
        ids.add(record["record_id"])
        execution_keys.add(record["execution_key"])
    return payload


def _expected(manifest, record_id):
    payload = _manifest(manifest)
    for record in payload["expected_records"]:
        if record["record_id"] == record_id:
            return payload, record
    _fail("UNEXPECTED_RECORD", "/record_id", "record is not pre-registered")


def seal_events(manifest: ExpectedManifest, record_id: str, observations: list[dict]) -> list[dict]:
    """Runner adapter: seal already observed events; never invent observations.

    Input events contain event/monotonic_ns/status/payload. The trusted runner
    supplies monotonic readings and event source; this function adds identities,
    contiguous sequence and hash-chain fields without claiming clocks are valid.
    """
    payload, expected = _expected(manifest, record_id)
    profile = payload["context"]["authoritative_metadata"]["measurement_profile"]
    if type(observations) is not list:
        _fail("EVENT_SHAPE", "/events", "event array required")
    sealed, previous = [], "0" * 64
    for i, event in enumerate(observations):
        _obj(event, {"event", "monotonic_ns", "status", "payload"}, path="/events")
        _json_contract(event)
        bound = {**event, "sequence": i, "source_id": profile["event_source_id"],
                 "clock_id": profile["clock_id"], "execution_key": expected["execution_key"],
                 "previous_event_sha256": previous}
        bound["event_sha256"] = digest(bound)
        previous = bound["event_sha256"]
        sealed.append(bound)
    _validate_events(payload, expected, sealed)
    return json.loads(canonical(sealed))


def _validate_events(payload, expected, events):
    if type(events) is not list or len(events) < 2:
        _fail("EVENT_MISSING", "/events", "started and terminal events required")
    profile = payload["context"]["authoritative_metadata"]["measurement_profile"]
    previous, previous_time = "0" * 64, -1
    for sequence, event in enumerate(events):
        path = "/events/" + str(sequence)
        _obj(event, {"event", "monotonic_ns", "status", "payload", "sequence", "source_id",
                     "clock_id", "execution_key", "previous_event_sha256", "event_sha256"}, path=path)
        _json_contract(event)
        if type(event["sequence"]) is not int or event["sequence"] != sequence:
            _fail("EVENT_SEQUENCE", path, "event sequence must be contiguous and unique")
        if type(event["monotonic_ns"]) is not int or event["monotonic_ns"] < previous_time or event["monotonic_ns"] < 0:
            _fail("EVENT_CLOCK", path, "monotonic nonnegative clock value required")
        if event["source_id"] != profile["event_source_id"] or event["clock_id"] != profile["clock_id"]:
            _fail("EVENT_SOURCE", path, "event source and clock must match bound measurement profile")
        if event["execution_key"] != expected["execution_key"]:
            _fail("EVENT_EXECUTION", path, "event execution identity differs")
        if type(event["event"]) is not str or event["event"] not in EVENT_TYPES:
            _fail("EVENT_TYPE", path, "unknown event kind")
        if type(event["status"]) is not str or not event["status"]:
            _fail("EVENT_STATUS", path, "event status required")
        if type(event["payload"]) is not dict:
            _fail("EVENT_SHAPE", path, "event payload object required")
        if event["previous_event_sha256"] != previous:
            _fail("EVENT_CHAIN", path, "event hash chain differs")
        actual = digest({key: value for key, value in event.items() if key != "event_sha256"})
        if event["event_sha256"] != actual:
            _fail("EVENT_CHAIN", path, "event content hash differs")
        previous, previous_time = actual, event["monotonic_ns"]
    if events[0]["event"] != "run_started" or events[-1]["event"] != "run_finished":
        _fail("EVENT_TERMINAL", "/events", "event stream requires run boundaries")
    if sum(e["event"] == "run_started" for e in events) != 1 or sum(e["event"] == "run_finished" for e in events) != 1:
        _fail("EVENT_TERMINAL", "/events", "exactly one start and terminal event required")
    if events[-1]["status"] not in TERMINAL:
        _fail("EVENT_TERMINAL", "/events", "unknown terminal status")


def make_sidecar(manifest: ExpectedManifest, record_id: str, events: list[dict], *,
                 terminal_status: str, verification_status: str) -> dict:
    """Runner adapter binding observations and independent verifier status."""
    payload, expected = _expected(manifest, record_id)
    _validate_events(payload, expected, events)
    if type(terminal_status) is not str or terminal_status not in TERMINAL:
        _fail("RECORD_STATUS", "/terminal_status", "unknown terminal status")
    if type(verification_status) is not str or verification_status not in {"PASS", "FAIL", "UNKNOWN"}:
        _fail("VERIFICATION_STATUS", "/verification", "independent verification status invalid")
    if events[-1]["status"] != terminal_status:
        _fail("EVENT_TERMINAL", "/terminal_status", "sidecar terminal and ledger terminal disagree")
    if terminal_status != "COMPLETED" and verification_status == "PASS":
        _fail("VERIFICATION_STATUS", "/verification", "incomplete run cannot be verified successful")
    context = payload["context"]["identity"]["context"]
    return {**{k: v for k, v in expected.items() if k != "identity_version"},
            "manifest_hash": manifest.manifest_hash,
            "context_hashes": {k: v for k, v in context.items() if k.endswith("_hash")},
            "events_sha256": digest(events), "event_count": len(events), "terminal_status": terminal_status,
            "verification": {"status": verification_status, "verifier_hash": context["verifier_hash"]}}


def validate_evidence(manifest: ExpectedManifest, records: list[dict],
                      event_ledgers: dict[str, list[dict]],
                      reference_records: list[dict] | None = None) -> dict:
    """Check a fixed expected denominator, sidecars, references, and event ledgers.

    Missing data produces EVIDENCE_INCOMPLETE with the unchanged denominator.
    Contradictory/duplicate/unplanned data raises a sanitized ContractError.
    Reference confirmation requires completed independent PASS evidence under
    the same context. Missing references affect coverage, never erase attempts.
    """
    payload = _manifest(manifest)
    if type(records) is not list or type(event_ledgers) is not dict:
        _fail("EVIDENCE_SHAPE", "", "sidecar array and ledger mapping required")
    if reference_records is None:
        reference_records = []
    if type(reference_records) is not list:
        _fail("EVIDENCE_SHAPE", "/references", "reference sidecar array required")
    expected = {entry["record_id"]: entry for entry in payload["expected_records"]}
    context = payload["context"]["identity"]["context"]
    received, confirmed, missing_events = set(), [], []
    for group, role in ((records, "MODEL"), (reference_records, "REFERENCE")):
        for record in group:
            _obj(record, SIDECAR_FIELDS, path="/records")
            _json_contract(record)
            ident = record["record_id"]
            if type(ident) is not str or ident not in expected:
                _fail("UNEXPECTED_RECORD", "/records", "record not present in frozen manifest")
            if ident in received:
                _fail("DUPLICATE_RECORD", "/records", "duplicate actual record identity")
            received.add(ident)
            wanted = expected[ident]
            if wanted["record_role"] != role or record["record_role"] != role:
                _fail("RECORD_ROLE", "/records", "record role differs from pre-registration")
            for field, value in wanted.items():
                if field != "identity_version" and record[field] != value:
                    _fail("SIDECAR_IDENTITY", "/records/" + field, "sidecar identity differs from expected record")
            if record["manifest_hash"] != manifest.manifest_hash:
                _fail("MANIFEST_IDENTITY", "/records/manifest_hash", "expected manifest differs")
            if record["context_hashes"] != {key: value for key, value in context.items() if key.endswith("_hash")}:
                _fail("SIDECAR_CONTEXT", "/records/context_hashes", "context components differ")
            _obj(record["verification"], {"status", "verifier_hash"}, path="/records/verification")
            if record["verification"]["verifier_hash"] != context["verifier_hash"]:
                _fail("VERIFIER_IDENTITY", "/records/verification", "independent verifier identity differs")
            status, verified = record["terminal_status"], record["verification"]["status"]
            if type(status) is not str or status not in TERMINAL or type(verified) is not str or verified not in {"PASS", "FAIL", "UNKNOWN"}:
                _fail("RECORD_STATUS", "/records", "invalid terminal or verification status")
            if status != "COMPLETED" and verified == "PASS":
                _fail("VERIFICATION_STATUS", "/records", "incomplete run cannot be verified successful")
            _hash(record["events_sha256"], "/records/events_sha256")
            if type(record["event_count"]) is not int or record["event_count"] < 2:
                _fail("EVENT_COUNT", "/records/event_count", "event count must include run boundaries")
            if ident not in event_ledgers:
                missing_events.append(ident)
                continue
            events = event_ledgers[ident]
            _validate_events(payload, wanted, events)
            if digest(events) != record["events_sha256"] or len(events) != record["event_count"]:
                _fail("EVENT_LEDGER_HASH", "/records/events_sha256", "ledger differs from sealed sidecar")
            if events[-1]["status"] != status:
                _fail("EVENT_TERMINAL", "/records/terminal_status", "ledger and terminal record disagree")
            if role == "REFERENCE" and status == "COMPLETED" and verified == "PASS":
                confirmed.append(ident)
    if set(event_ledgers) - received:
        _fail("ORPHAN_LEDGER", "/events", "ledger without registered actual sidecar")
    missing = sorted(set(expected) - received)
    model_expected = sum(r["record_role"] == "MODEL" for r in expected.values())
    ref_expected = len(expected) - model_expected
    complete = not missing and not missing_events
    return {"status": "EVIDENCE_BOUND" if complete else "EVIDENCE_INCOMPLETE",
            "manifest_hash": manifest.manifest_hash,
            "comparison_context_hash": payload["context"]["identity"]["comparison_context_hash"],
            "expected_count": len(expected), "model_denominator": model_expected,
            "reference_denominator": ref_expected, "observed_count": len(received),
            "missing_record_ids": missing, "missing_event_record_ids": sorted(missing_events),
            "confirmed_reference_ids": sorted(confirmed), "formal_ready": False,
            "runtime_enforcement": "NOT_VERIFIED", "measurement_validity": "NOT_VERIFIED"}
