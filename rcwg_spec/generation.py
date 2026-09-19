"""Offline P0/P1 assembly and private response evidence; never calls a provider.

Only validated public TaskInput crosses the message boundary. Source templates are
read as bytes and their hashes are recorded separately from rendered messages.
The mock adapter is deliberately a serializer, not an API client or tokenizer.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from .common import ContractError, canonical, digest
from .ir_structure import _json_value, parse_ir_bytes
from .public_task import validate_public_task

ROOT = Path(__file__).resolve().parents[1]
LOGICAL_FIELDS = frozenset({"required_outputs", "hard_constraints", "necessary_operations",
                            "data_dependencies", "information_requirements",
                            "permissible_alternatives", "uncertainty"})
OPTIONAL_EMPTY = frozenset({"permissible_alternatives", "uncertainty"})
TOKEN_LIMITS = {("P0", "physical"): 16384, ("P1", "logical"): 4096,
                ("P1", "physical"): 12288}
CAPABILITY_FIELDS = frozenset({"max_output_tokens", "tokenizer", "seed", "structured_json"})
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _fail(code, path="", detail="generation contract rejected"):
    raise ContractError(code, path, detail) from None


def _id(value, path):
    if type(value) is not str or not ID.fullmatch(value):
        _fail("GENERATION_ID", path, "bounded identifier required")
    return value


def validate_logical_contract(value: dict) -> dict:
    """Closed seven-field schema; values are arrays of public planning strings."""
    _json_value(value)
    if type(value) is not dict or set(value) != LOGICAL_FIELDS:
        _fail("LOGICAL_SCHEMA", "", "exactly seven logical-contract fields required")
    for field in sorted(LOGICAL_FIELDS):
        arr = value[field]
        if type(arr) is not list or (field not in OPTIONAL_EMPTY and not arr):
            _fail("LOGICAL_SCHEMA", "/" + field, "string array required; required claims cannot be empty")
        if any(type(item) is not str or not item.strip() for item in arr):
            _fail("LOGICAL_SCHEMA", "/" + field, "only nonempty strings permitted")
    if len(canonical(value)) > 65536:
        _fail("IR_INPUT_LIMIT", "", "logical contract exceeds final JSON byte limit")
    return deepcopy(value)


def parse_response(raw: bytes, *, kind: str) -> dict:
    """Strict UTF-8, duplicate-free JSON. No fences, extraction, repair or retry."""
    if type(kind) is not str or kind not in {"logical", "physical"}:
        _fail("GENERATION_STAGE", "/kind", "unknown response stage")
    parsed = parse_ir_bytes(raw)
    if kind == "logical":
        parsed = validate_logical_contract(parsed)
    return {"value": parsed, "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_sha256": digest(parsed), "raw_bytes": len(raw),
            "status": "PARSED", "semantic_validation": "NOT_PERFORMED"}


def _capabilities(value):
    if value is None:
        return {key: "UNKNOWN" for key in sorted(CAPABILITY_FIELDS)}
    if type(value) is not dict or set(value) != CAPABILITY_FIELDS:
        _fail("PROVIDER_CAPABILITY", "/capabilities", "complete closed capability map required")
    if any(type(x) is not str or x not in {"SUPPORTED", "UNSUPPORTED", "UNKNOWN"}
           for x in value.values()):
        _fail("PROVIDER_CAPABILITY", "/capabilities", "capability status invalid")
    return deepcopy(value)


def build_request(task: dict, *, protocol: str, stage: str,
                  generation_attempt_id: str, request_id: str,
                  logical_contract: dict | None = None,
                  capabilities: dict | None = None, token_counter=None,
                  tokenizer_id: str | None = None) -> dict:
    """Render a mock-provider request from public input and pinned local sources.

    A token counter, if supplied, is a trusted runner callback over the exact
    serialized provider bytes; its count is input measurement, never API usage.
    """
    if type(protocol) is not str or type(stage) is not str or (protocol, stage) not in TOKEN_LIMITS:
        _fail("GENERATION_STAGE", "/stage", "invalid protocol and stage combination")
    _id(generation_attempt_id, "/generation_attempt_id")
    _id(request_id, "/request_id")
    if tokenizer_id is not None:
        _id(tokenizer_id, "/tokenizer_id")
    checked = validate_public_task(task)
    if protocol == "P1" and stage == "physical":
        logical = validate_logical_contract(logical_contract)
    elif logical_contract is not None:
        _fail("LOGICAL_UNEXPECTED", "/logical_contract", "logical contract belongs only to P1 physical stage")
    else:
        logical = None
    caps = _capabilities(capabilities)
    template_name = "p0_user.txt" if protocol == "P0" else "p1_" + stage + ".txt"
    source_paths = {"system": ROOT / "prompts/v1_1/system.txt",
                    "template": ROOT / "prompts/v1_1" / template_name,
                    "operator_catalog": ROOT / "specs/reference_v1_0/catalogs/operators.json",
                    "workflow_schema": ROOT / "specs/reference_v1_0/schemas/workflow.schema.json",
                    "example_json": ROOT / "specs/reference_v1_0/examples/workflow_topk.json",
                    "approved_contract_worklist": ROOT / "specs/spec001b/operator_contract_worklist.json",
                    "schema_addendum": ROOT / "specs/spec001b/generation_schema_addendum.json"}
    sources = {name: path.read_bytes() for name, path in source_paths.items()}
    replacements = {"task_json": canonical(checked["normalized_task"]).decode("utf8"),
                    "operator_catalog": sources["operator_catalog"].decode("utf8"),
                    "workflow_schema": sources["workflow_schema"].decode("utf8"),
                    "example_json": sources["example_json"].decode("utf8"),
                    "logical_contract": canonical(logical).decode("utf8") if logical is not None else ""}
    # Single-pass replacement: public text containing {{...}} is data and cannot
    # recursively substitute another task/catalog/template placeholder.
    template = sources["template"].decode("utf8")
    rendered = re.sub(r"\{\{([a-z_]+)\}\}", lambda m: replacements[m.group(1)], template)
    # Versioned public planning decisions supplement the protected legacy card.
    # Historical implementation-status labels are not generation instructions.
    worklist = json.loads(sources["approved_contract_worklist"])
    planning_fields = {"operator", "implementations", "input_ports", "output_ports",
                       "required_parameters", "optional_parameters", "static_rules", "runtime_obligations"}
    supplement = {"source": "Approved SPEC001B design worklist; executable validation uses the current compiler registry",
                  "operators": [{key: value for key, value in row.items() if key in planning_fields}
                                for row in worklist["operators"]]}
    messages = [{"role": "system", "content": sources["system"].decode("utf8")},
                {"role": "system", "content": sources["schema_addendum"].decode("utf8")},
                {"role": "system", "content": canonical(supplement).decode("utf8")},
                {"role": "user", "content": rendered}]
    payload = {"adapter": "RCWG_MOCK_SERIALIZER_0.1", "messages": messages,
               "requested_max_output_tokens": TOKEN_LIMITS[(protocol, stage)]}
    provider_bytes = canonical(payload)
    measured = None
    if token_counter is not None:
        if not callable(token_counter) or caps["tokenizer"] != "SUPPORTED":
            _fail("INPUT_TOKENIZER", "/tokenizer", "trusted supported tokenizer required")
        _id(tokenizer_id, "/tokenizer_id")
        try:
            measured = token_counter(provider_bytes)
        except Exception:
            _fail("INPUT_TOKENIZER", "/tokenizer", "tokenizer failed without exposing request text")
        if type(measured) is not int or measured < 0:
            _fail("INPUT_TOKENIZER", "/tokenizer", "tokenizer must return a nonnegative integer")
        if measured > 12288:
            _fail("INPUT_BUDGET_EXCEEDED", "/input_tokens", "dataset-build input budget exceeded")
    blockers = ["MOCK_ONLY", "API_SERVICE_NOT_FROZEN"]
    blockers.extend("CAPABILITY_" + key.upper() + "_" + status
                    for key, status in sorted(caps.items()) if status != "SUPPORTED")
    if measured is None:
        blockers.append("INPUT_TOKEN_COUNT_UNKNOWN")
    return {"protocol": protocol, "stage": stage, "generation_attempt_id": generation_attempt_id,
            "request_id": request_id, "request_kind": "MOCK", "provider_payload": payload,
            "provider_serialized": provider_bytes.decode("utf8"),
            "provider_request_sha256": hashlib.sha256(provider_bytes).hexdigest(),
            "task_input_hash": checked["task_input_hash"],
            "normalized_input_hash": checked["normalized_input_hash"],
            "logical_contract_hash": digest(logical) if logical is not None else None,
            "planning_supplement_sha256": digest(supplement),
            "source_hashes": {name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
            "budget": {"max_input_tokens": 12288, "max_output_tokens": TOKEN_LIMITS[(protocol, stage)],
                       "max_final_json_bytes": 65536},
            "input_token_measurement": {"value": measured, "tokenizer_id": tokenizer_id,
                                        "status": "MEASURED" if measured is not None else "UNKNOWN"},
            "capabilities": caps, "actual_usage": None, "real_requests": 0,
            "formal_ready": False, "freeze_blockers": blockers}


def run_mock_generation(task: dict, *, protocol: str, responses: list[bytes],
                        generation_attempt_id: str, request_ids: list[str] | None = None) -> dict:
    """Record one P0 stage or two P1 stages within one plan-generation attempt.

    Invalid logical output terminates that attempt; it does not silently repair,
    regenerate, execute, or make the physical request without a valid contract.
    """
    if type(protocol) is not str or protocol not in {"P0", "P1"}:
        _fail("GENERATION_STAGE", "/protocol", "unknown protocol")
    _id(generation_attempt_id, "/generation_attempt_id")
    stages = ["physical"] if protocol == "P0" else ["logical", "physical"]
    if type(responses) is not list or len(responses) != len(stages):
        _fail("MOCK_RESPONSES", "/responses", "one response fixture per planned stage required")
    if request_ids is None:
        request_ids = [generation_attempt_id + "." + s for s in stages]
    if type(request_ids) is not list or len(request_ids) != len(stages):
        _fail("GENERATION_ID", "/request_ids", "one unique request identifier per stage required")
    for value in request_ids:
        _id(value, "/request_ids")
    if len(set(request_ids)) != len(request_ids):
        _fail("GENERATION_ID", "/request_ids", "duplicate request identifiers")
    records, logical, final_plan = [], None, None
    status = "MOCK_GENERATION_PARSED"
    for stage, raw, request_id in zip(stages, responses, request_ids):
        request = build_request(task, protocol=protocol, stage=stage,
                                generation_attempt_id=generation_attempt_id,
                                request_id=request_id, logical_contract=logical)
        record = {"request": request, "transport_retry_index": 0, "regeneration_index": 0,
                  "execution_repeat_id": None, "actual_usage": None}
        try:
            parsed = parse_response(raw, kind=stage)
        except ContractError as error:
            record["response"] = {"status": "RESPONSE_INVALID", "code": error.code,
                                  "path": error.path, "raw_sha256":
                                  hashlib.sha256(raw).hexdigest() if type(raw) is bytes else None}
            records.append(record)
            status = "MOCK_RESPONSE_INVALID"
            break
        record["response"] = parsed
        records.append(record)
        if stage == "logical":
            logical = parsed["value"]
        else:
            final_plan = parsed["value"]
    return {"status": status, "protocol": protocol, "generation_attempt_id": generation_attempt_id,
            "plan_generation_attempts": 1, "planned_mock_requests": len(stages),
            "mock_requests": len(records), "real_requests": 0, "records": records,
            "plan": final_plan, "actual_usage": None, "formal_ready": False,
            "runtime_status": "NOT_IMPLEMENTED", "plan_validation": "NOT_PERFORMED"}


def archive_response(private_root: str | Path, archive_id: str, raw: bytes, *, kind: str) -> dict:
    """Create a private exclusive archive strictly below this checkout's runs/.

    The archive stores invalid responses too; the return value contains hashes
    and safe codes only. Incomplete writes remain visible for recovery; no retry
    overwrites evidence. The runs directory is excluded by repository policy.
    """
    if type(raw) is not bytes:
        _fail("ARCHIVE_INPUT", "", "raw bytes required")
    if type(archive_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", archive_id):
        _fail("ARCHIVE_ID", "", "safe archive identifier required")
    if type(kind) is not str or kind not in {"logical", "physical"}:
        _fail("GENERATION_STAGE", "/kind", "unknown response stage")
    allowed = ROOT / "runs"
    try:
        candidate = Path(private_root).absolute()
        relative = candidate.relative_to(allowed.absolute())
        current = allowed
        for segment in [None, *relative.parts]:
            if segment is not None:
                current = current / segment
            if current.is_symlink():
                _fail("ARCHIVE_PRIVATE_PATH", "", "private archive cannot traverse symlinks")
        if not candidate.resolve().is_relative_to(allowed.absolute()):
            _fail("ARCHIVE_PRIVATE_PATH", "", "private archive must remain in runs")
    except (TypeError, ValueError, OSError):
        _fail("ARCHIVE_PRIVATE_PATH", "", "private archive must remain in runs")
    metadata = {"status": "RESPONSE_INVALID", "kind": kind, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_bytes": len(raw), "canonical_sha256": None, "parse_error": None,
                "private": True, "formal_ready": False}
    parsed = None
    try:
        parsed = parse_response(raw, kind=kind)
        metadata.update(status="PARSED", canonical_sha256=parsed["canonical_sha256"])
    except ContractError as error:
        metadata["parse_error"] = {"code": error.code, "path": error.path}
    try:
        candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = candidate / archive_id
        directory.mkdir(mode=0o700)
        contents = {"response.raw": raw, "metadata.json": canonical(metadata)}
        if parsed is not None:
            contents["response.canonical.json"] = canonical(parsed["value"])
        for name, body in contents.items():
            fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
    except FileExistsError:
        _fail("ARCHIVE_EXISTS", "", "archive already exists; overwrite forbidden")
    except OSError:
        _fail("ARCHIVE_IO", "", "private evidence write failed")
    return {**metadata, "archive_id": archive_id}
