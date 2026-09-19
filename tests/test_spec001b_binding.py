"""BOOT_ONLY runner identity, fixed-denominator and event corruption tests."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
import unittest
import uuid

from rcwg_spec.common import ContractError, canonical, digest
from rcwg_spec.generation import ROOT
from rcwg_spec.public_task import validate_public_task
from rcwg_spec.binding import (build_context, freeze_expected, seal_events, make_sidecar,
                               validate_evidence, ExpectedManifest, RunnerContext)


def public_task():
    task = json.loads((ROOT / "specs/reference_v1_0/examples/task_input.json").read_bytes())
    task["datasets"][0].update(kind="table", revision="fixture-v1", schema_source="public-fixture",
                                data_sha256=hashlib.sha256(b"BOOT_ONLY synthetic data").hexdigest())
    return task


def context_arguments(task=None):
    task = public_task() if task is None else task
    sources = validate_public_task(task)["source_manifest"]
    return {"condition_id": "C0", "data_manifest": [{"id": entry["id"], "revision": entry["revision"],
             "content_sha256": entry["data_sha256"], "schema_hash": entry["schema_hash"]} for entry in sources],
            "runtime": {"revision": "runtime-v1", "implementation": "BOOT_ONLY"},
            "cache_policy": {"revision": "cache-v1", "mode": "cold"},
            "verifier": {"revision": "verifier-v1", "implementation": "fixture"},
            "metric_spec": {"revision": "metrics-v1", "mode": "ENGINEERING_ONLY"},
            "measurement_profile": {"revision": "measurement-v1", "event_source_id": "worker-1", "clock_id": "clock-1"},
            "operator_registry": {"revision": "registry-v1", "operators": ["fixture"]},
            "source_manifest": {"revision": "source-v1", "public_sources": sources}}


def spec(record_id="model-1", *, role="MODEL", plan_extra=0, repeat_id="repeat-1", repeat_role="PRIMARY_REPEAT"):
    return {"record_id": record_id, "record_role": role,
            "plan": {"task_id": public_task()["task_id"], "nodes": [], "fixture_variant": plan_extra},
            "compiler_source": b"BOOT_ONLY compiler source fixture", "generation_id": record_id + "-generation",
            "repeat_id": repeat_id, "repeat_role": repeat_role}


def fixture_manifest():
    context = build_context(public_task(), **context_arguments())
    manifest = freeze_expected(context, [spec(), spec("model-2", repeat_id="repeat-2"),
                                        spec("reference-1", role="REFERENCE", plan_extra=1)])
    return context, manifest


def observations(status="COMPLETED"):
    return [{"event": "run_started", "monotonic_ns": 10, "status": "RUNNING", "payload": {}},
            {"event": "node_started", "monotonic_ns": 20, "status": "RUNNING", "payload": {"node": "fixture"}},
            {"event": "run_finished", "monotonic_ns": 30, "status": status, "payload": {}}]


def evidence(manifest):
    ledgers, model, references = {}, [], []
    for entry in manifest.as_dict()["expected_records"]:
        ident = entry["record_id"]
        events = seal_events(manifest, ident, observations())
        ledgers[ident] = events
        record = make_sidecar(manifest, ident, events, terminal_status="COMPLETED", verification_status="PASS")
        (model if entry["record_role"] == "MODEL" else references).append(record)
    return model, ledgers, references


class BindingTests(unittest.TestCase):
    def test_actual_context_components_and_inputs_are_hashed(self):
        task, args = public_task(), context_arguments()
        context = build_context(task, **args)
        content = context.as_dict()
        bound = content["identity"]["context"]
        for name in ("runtime", "cache_policy", "verifier", "metric_spec", "measurement_profile", "operator_registry", "source_manifest"):
            self.assertEqual(bound[name + "_hash"], digest(args[name]))
        self.assertEqual(bound["resource_profile_hash"], digest(task["resources"]))
        self.assertEqual(content["task_input_hash"], digest(task))
        self.assertFalse(content["formal_ready"])

    def test_all_comparison_dimensions_change_context_hash(self):
        task, args = public_task(), context_arguments()
        original = build_context(task, **args).comparison_context_hash
        for component in ("runtime", "cache_policy", "verifier", "metric_spec", "measurement_profile", "operator_registry", "source_manifest"):
            changed = deepcopy(args)
            changed[component]["revision"] += "-changed"
            with self.subTest(component=component):
                self.assertNotEqual(build_context(task, **changed).comparison_context_hash, original)
        changed = deepcopy(args)
        changed["condition_id"] = "C1"
        self.assertNotEqual(build_context(task, **changed).comparison_context_hash, original)
        altered = deepcopy(task)
        altered["resources"]["wall_timeout_s"] += 1
        self.assertNotEqual(build_context(altered, **context_arguments(altered)).comparison_context_hash, original)
        altered = deepcopy(task)
        altered["datasets"][0]["data_sha256"] = "a" * 64
        self.assertNotEqual(build_context(altered, **context_arguments(altered)).comparison_context_hash, original)

    def test_data_identity_mismatch_missing_duplicate_and_extra_rejected(self):
        for dimension in ("revision", "content_sha256", "schema_hash"):
            args = context_arguments()
            args["data_manifest"][0][dimension] = "different" if dimension == "revision" else "b" * 64
            with self.subTest(dimension=dimension), self.assertRaises(ContractError):
                build_context(public_task(), **args)
        for mutation in ("missing", "duplicate", "extra"):
            args = context_arguments()
            if mutation == "missing":
                args["data_manifest"] = []
            else:
                args["data_manifest"].append(deepcopy(args["data_manifest"][0]))
                if mutation == "extra":
                    args["data_manifest"][-1]["id"] = "dataset:unknown"
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                build_context(public_task(), **args)

    def test_source_registry_must_bind_public_sources(self):
        args = context_arguments()
        args["source_manifest"]["public_sources"] = []
        with self.assertRaises(ContractError) as caught:
            build_context(public_task(), **args)
        self.assertEqual(caught.exception.code, "SOURCE_MANIFEST_MISMATCH")

    def test_missing_or_unresolved_metadata_blocks_binding(self):
        for component in ("runtime", "cache_policy", "verifier", "metric_spec", "measurement_profile", "operator_registry", "source_manifest"):
            for bad in (None, {}, {"revision": "UNRESOLVED"}, {"revision": "known", "nested": {"hash": None}}):
                args = context_arguments()
                args[component] = bad
                with self.subTest(component=component, bad=bad), self.assertRaises(ContractError):
                    build_context(public_task(), **args)

    def test_legacy_missing_content_or_revision_not_promoted_to_formal_identity(self):
        for missing in ("data_sha256", "revision"):
            task = public_task()
            del task["datasets"][0][missing]
            if missing == "revision":
                del task["datasets"][0]["kind"]
            args = context_arguments(task)
            with self.subTest(missing=missing), self.assertRaises(ContractError):
                build_context(task, **args)

    def test_context_snapshot_immutable_and_defensive_copies(self):
        task, args = public_task(), context_arguments()
        context = build_context(task, **args)
        initial = context.comparison_context_hash
        task["instruction"] = "changed"
        args["runtime"]["revision"] = "changed"
        returned = context.as_dict()
        returned["identity"]["context"]["runtime_hash"] = "f" * 64
        self.assertEqual(context.comparison_context_hash, initial)
        with self.assertRaises(FrozenInstanceError):
            context._snapshot = b"{}"

    def test_expected_hashes_actual_plan_compiler_and_preserves_order(self):
        context, _ = fixture_manifest()
        specs = [spec("z"), spec("a", plan_extra=1)]
        manifest = freeze_expected(context, specs)
        records = manifest.as_dict()["expected_records"]
        self.assertEqual([row["record_id"] for row in records], ["z", "a"])
        self.assertEqual(records[0]["plan_hash"], digest(specs[0]["plan"]))
        self.assertEqual(records[0]["compiler_hash"], hashlib.sha256(specs[0]["compiler_source"]).hexdigest())
        specs[0]["plan"]["nodes"].append("changed")
        self.assertEqual(manifest.as_dict()["expected_records"], records)

    def test_repeat_role_plan_and_compiler_change_execution_key(self):
        context, _ = fixture_manifest()
        original = freeze_expected(context, [spec()]).as_dict()["expected_records"][0]
        for field in ("plan", "compiler_source", "generation_id", "repeat_id", "repeat_role"):
            value = spec()
            if field == "plan":
                value[field]["fixture_variant"] = 1
            elif field == "compiler_source":
                value[field] += b" changed"
            elif field == "repeat_role":
                value[field] = "TIMING_CONFIRMATION"
            else:
                value[field] += "-changed"
            changed = freeze_expected(context, [value]).as_dict()["expected_records"][0]
            with self.subTest(field=field):
                self.assertNotEqual(original["execution_key"], changed["execution_key"])
                self.assertEqual(original["comparison_context_hash"], changed["comparison_context_hash"])

    def test_reference_plan_differs_but_same_context_confirmed(self):
        _, manifest = fixture_manifest()
        model, ledgers, refs = evidence(manifest)
        self.assertNotEqual(model[0]["plan_hash"], refs[0]["plan_hash"])
        report = validate_evidence(manifest, model, ledgers, refs)
        self.assertEqual(report["status"], "EVIDENCE_BOUND")
        self.assertEqual(report["confirmed_reference_ids"], ["reference-1"])
        self.assertEqual((report["model_denominator"], report["reference_denominator"]), (2, 1))
        self.assertFalse(report["formal_ready"])

    def test_missing_expected_record_does_not_shrink_denominator(self):
        _, manifest = fixture_manifest()
        model, ledgers, refs = evidence(manifest)
        model.pop()
        del ledgers["model-2"]
        report = validate_evidence(manifest, model, ledgers, refs)
        self.assertEqual(report["status"], "EVIDENCE_INCOMPLETE")
        self.assertEqual(report["expected_count"], 3)
        self.assertEqual(report["model_denominator"], 2)
        self.assertEqual(report["missing_record_ids"], ["model-2"])

    def test_expected_manifest_cannot_be_modified_by_returned_dictionary(self):
        _, manifest = fixture_manifest()
        returned = manifest.as_dict()
        returned["expected_records"].pop()
        model, ledgers, refs = evidence(manifest)
        self.assertEqual(validate_evidence(manifest, model, ledgers, refs)["expected_count"], 3)
        with self.assertRaises(FrozenInstanceError):
            manifest._snapshot = canonical(returned)
        with self.assertRaises(ContractError):
            validate_evidence(returned, model, ledgers, refs)

    def test_missing_reference_keeps_model_denominator_and_reference_obligation(self):
        _, manifest = fixture_manifest()
        model, ledgers, _ = evidence(manifest)
        del ledgers["reference-1"]
        report = validate_evidence(manifest, model, ledgers)
        self.assertEqual(report["model_denominator"], 2)
        self.assertEqual(report["reference_denominator"], 1)
        self.assertEqual(report["confirmed_reference_ids"], [])
        self.assertEqual(report["missing_record_ids"], ["reference-1"])

    def test_missing_events_never_confirm_reference(self):
        _, manifest = fixture_manifest()
        model, ledgers, refs = evidence(manifest)
        del ledgers["reference-1"]
        report = validate_evidence(manifest, model, ledgers, refs)
        self.assertEqual(report["status"], "EVIDENCE_INCOMPLETE")
        self.assertEqual(report["missing_event_record_ids"], ["reference-1"])
        self.assertEqual(report["confirmed_reference_ids"], [])

    def test_duplicate_unexpected_wrong_role_and_orphan_rejected(self):
        for mutation in ("duplicate", "unexpected", "role", "orphan"):
            _, manifest = fixture_manifest()
            model, ledgers, refs = evidence(manifest)
            if mutation == "duplicate":
                model.append(deepcopy(model[0]))
            elif mutation == "unexpected":
                model[0]["record_id"] = "unplanned"
            elif mutation == "role":
                model[0]["record_role"] = "REFERENCE"
            else:
                ledgers["unplanned"] = []
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_evidence(manifest, model, ledgers, refs)

    def test_cache_runtime_source_sidecar_tampering_rejected(self):
        for field in ("runtime_hash", "cache_policy_hash", "source_manifest_hash", "resource_profile_hash", "metric_spec_hash", "measurement_profile_hash", "operator_registry_hash"):
            _, manifest = fixture_manifest()
            model, ledgers, refs = evidence(manifest)
            model[0]["context_hashes"][field] = "f" * 64
            with self.subTest(field=field):
                with self.assertRaises(ContractError) as caught:
                    validate_evidence(manifest, model, ledgers, refs)
                self.assertEqual(caught.exception.code, "SIDECAR_CONTEXT")

    def test_identity_manifest_verifier_and_reference_tampering_rejected(self):
        for field in ("execution_key", "plan_hash", "compiler_hash", "input_hash", "comparison_context_hash", "manifest_hash", "verifier_hash"):
            _, manifest = fixture_manifest()
            model, ledgers, refs = evidence(manifest)
            target = refs[0]["verification"] if field == "verifier_hash" else refs[0]
            target[field] = "f" * 64
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_evidence(manifest, model, ledgers, refs)

    def test_event_drop_duplicate_reorder_source_clock_hash_and_execution(self):
        for mutation in ("drop", "duplicate", "reorder", "source_id", "clock_id", "execution_key", "monotonic_ns", "payload", "sequence", "previous_event_sha256"):
            _, manifest = fixture_manifest()
            model, ledgers, refs = evidence(manifest)
            events = ledgers["model-1"]
            if mutation == "drop":
                events.pop(1)
            elif mutation == "duplicate":
                events.insert(1, deepcopy(events[1]))
            elif mutation == "reorder":
                events[0], events[1] = events[1], events[0]
            elif mutation == "monotonic_ns":
                events[1][mutation] = 5
            elif mutation == "payload":
                events[1][mutation]["changed"] = True
            elif mutation == "sequence":
                events[1][mutation] = True
            else:
                events[1][mutation] = "forged"
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_evidence(manifest, model, ledgers, refs)

    def test_resealed_events_still_must_match_original_sidecar_hash(self):
        _, manifest = fixture_manifest()
        model, ledgers, refs = evidence(manifest)
        altered = observations()
        altered[1]["payload"] = {"changed": True}
        ledgers["model-1"] = seal_events(manifest, "model-1", altered)
        with self.assertRaises(ContractError) as caught:
            validate_evidence(manifest, model, ledgers, refs)
        self.assertEqual(caught.exception.code, "EVENT_LEDGER_HASH")

    def test_failed_and_unknown_attempts_remain_in_expected_records(self):
        _, manifest = fixture_manifest()
        for status in ("MODEL_FAILURE", "TIMEOUT", "OOM", "INFRA_FAILURE", "UNKNOWN"):
            model, ledgers, refs = evidence(manifest)
            events = seal_events(manifest, "model-1", observations(status))
            model[0] = make_sidecar(manifest, "model-1", events, terminal_status=status, verification_status="UNKNOWN")
            ledgers["model-1"] = events
            with self.subTest(status=status):
                report = validate_evidence(manifest, model, ledgers, refs)
                self.assertEqual(report["expected_count"], 3)
                self.assertEqual(report["observed_count"], 3)
                self.assertFalse(report["formal_ready"])

    def test_incomplete_run_cannot_have_successful_verification(self):
        _, manifest = fixture_manifest()
        events = seal_events(manifest, "model-1", observations("TIMEOUT"))
        with self.assertRaises(ContractError):
            make_sidecar(manifest, "model-1", events, terminal_status="TIMEOUT", verification_status="PASS")
        with self.assertRaises(ContractError):
            make_sidecar(manifest, "model-1", events, terminal_status="COMPLETED", verification_status="PASS")

    def test_sealer_requires_observations_run_boundaries_and_clock_order(self):
        _, manifest = fixture_manifest()
        for values in ([], observations()[1:], observations()[:-1], list(reversed(observations()))):
            with self.assertRaises(ContractError):
                seal_events(manifest, "model-1", values)

    def test_expected_specs_reject_wrong_case_duplicates_bad_roles_and_claimed_hash(self):
        context, _ = fixture_manifest()
        for mutation in ("case", "duplicate", "repeat_role", "role", "hash"):
            row = spec()
            rows = [row]
            if mutation == "case":
                row["plan"]["task_id"] = "other-case"
            elif mutation == "duplicate":
                rows.append(deepcopy(row))
            elif mutation == "repeat_role":
                row["repeat_role"] = []
            elif mutation == "role":
                row["record_role"] = "MODEL_SUBMITTED_REFERENCE"
            else:
                row["plan_hash"] = "a" * 64
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                freeze_expected(context, rows)

    def test_untrusted_errors_redact_unknown_names_and_values(self):
        _, manifest = fixture_manifest()
        model, ledgers, refs = evidence(manifest)
        canary = uuid.uuid4().hex
        model[0][canary] = canary
        with self.assertRaises(ContractError) as caught:
            validate_evidence(manifest, model, ledgers, refs)
        self.assertNotIn(canary, str(caught.exception))

    def test_malformed_json_and_large_numeric_metadata_are_structured(self):
        for bad in (float("nan"), 2**64000, "\ud800", object()):
            args = context_arguments()
            args["runtime"]["bad_metadata"] = bad
            with self.subTest(kind=type(bad).__name__), self.assertRaises(ContractError):
                build_context(public_task(), **args)
        _, manifest = fixture_manifest()
        values = observations()
        values[1]["payload"]["count"] = 2**64000
        with self.assertRaises(ContractError):
            seal_events(manifest, "model-1", values)

    def test_no_model_metadata_dictionary_can_replace_runner_context(self):
        with self.assertRaises(ContractError) as caught:
            freeze_expected({"runtime_hash": "a" * 64}, [spec()])
        self.assertEqual(caught.exception.code, "RUNNER_CONTEXT_REQUIRED")

    def test_corrupt_snapshot_constructors_raise_structured_errors(self):
        for raw in (b'{}', b'[]', b'{"bad":', b'{"x":1,"x":2}', b' { } ', None):
            with self.subTest(raw_type=type(raw).__name__):
                with self.assertRaises(ContractError):
                    freeze_expected(RunnerContext(raw), [spec()])
                with self.assertRaises(ContractError):
                    validate_evidence(ExpectedManifest(raw), [], {})
                with self.assertRaises(ContractError):
                    _ = RunnerContext(raw).comparison_context_hash
                with self.assertRaises(ContractError):
                    _ = ExpectedManifest(raw).manifest_hash
        _, manifest = fixture_manifest()
        corrupted = manifest.as_dict()
        corrupted["expected_records"][0]["execution_key"] = "f" * 64
        with self.assertRaises(ContractError):
            validate_evidence(ExpectedManifest(canonical(corrupted)), [], {})


if __name__ == "__main__":
    unittest.main()
