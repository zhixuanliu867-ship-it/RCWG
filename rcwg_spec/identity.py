"""Pure identity builders for SPEC-001B; no run execution or data materialization.

A context hash binds compatible measurements; it is not proof that the recorded
configuration was enforced. Source hashes must come from trusted evidence writers.
Candidate references share comparison_context_hash, NOT plan_hash.
"""
from __future__ import annotations
from copy import deepcopy
import re
from .common import ContractError, keys, text, digest

HASH = re.compile(r"[0-9a-f]{64}\Z")
CONTEXT_HASHES = frozenset({"data_manifest_hash", "resource_profile_hash", "runtime_hash",
                          "cache_policy_hash", "verifier_hash", "metric_spec_hash",
                          "measurement_profile_hash", "operator_registry_hash",
                          "source_manifest_hash"})
CONTEXT_TEXT = frozenset({"case_id", "condition_id"})


def _hash(x, path):
    if type(x) is not str or not HASH.fullmatch(x):
        raise ContractError("IDENTITY_HASH", path, "lowercase SHA256 hex required")


def comparison_identity(context: dict) -> dict:
    keys(context, CONTEXT_HASHES | CONTEXT_TEXT, set(), "comparison_context")
    for k in CONTEXT_HASHES:
        _hash(context[k], "comparison_context." + k)
    for k in CONTEXT_TEXT:
        text(context[k], "comparison_context." + k)
    payload = {"identity_version": "SPEC001B_ID_0.1", "context": deepcopy(context)}
    return {**payload, "comparison_context_hash": digest(payload)}


def execution_identity(context: dict, *, plan_hash: str, compiler_hash: str,
                       input_hash: str, generation_id: str, repeat_id: str,
                       repeat_role: str = "PRIMARY_REPEAT") -> dict:
    compared = comparison_identity(context)
    for name, x in (("plan_hash", plan_hash), ("compiler_hash", compiler_hash),
                    ("input_hash", input_hash)):
        _hash(x, name)
    for name, x in (("generation_id", generation_id), ("repeat_id", repeat_id)):
        text(x, name)
    if type(repeat_role) is not str or repeat_role not in {"PRIMARY_REPEAT", "TIMING_CONFIRMATION"}:
        raise ContractError("REPEAT_ROLE", "repeat_role", "unknown repetition role")
    payload = {"identity_version": "SPEC001B_ID_0.1",
               "comparison_context_hash": compared["comparison_context_hash"],
               "plan_hash": plan_hash, "compiler_hash": compiler_hash,
               "input_hash": input_hash, "generation_id": generation_id,
               "repeat_id": repeat_id, "repeat_role": repeat_role}
    return {**payload, "execution_key": digest(payload)}


def require_same_context(left: dict, right: dict) -> str:
    a = comparison_identity(left)["comparison_context_hash"]
    b = comparison_identity(right)["comparison_context_hash"]
    if a != b:
        raise ContractError("COMPARISON_CONTEXT_MISMATCH", "comparison_context",
                            "data, condition, runtime or measurement identities differ")
    return a
