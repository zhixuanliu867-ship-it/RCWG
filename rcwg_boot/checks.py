"""Bootstrap integrity checks, with a separate fail-closed formal gate."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def check(root: Path = ROOT) -> dict:
    config = load(root / "configs/boot.json")
    expected = {"cpu": 1, "memory_gib": 1, "tasks": 1, "parallelism": 1,
                "max_retries": 0, "timeout_s": 120}
    if config["job"] != expected or config["formal_run_enabled"] or config["api_default"] != "mock":
        raise ValueError("BOOT safety defaults changed; an explicit reviewed amendment is required")
    if config["cloud_api_probe_enabled"]:
        raise ValueError("Live API probes are local/manual only in BOOT-001")
    inventory = load(root / "provenance/SOURCE_INVENTORY.json")
    count = 0
    for archive in inventory["archives"]:
        for member in archive["members"]:
            name = member["path"]
            if name.startswith("spec_bundle/"):
                target = root / "specs/reference_v1_0" / name.split("/", 1)[1]
            elif "/prompts_v1.1/" in name:
                target = root / "prompts/v1_1" / name.split("/prompts_v1.1/", 1)[1]
            else:
                continue
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != member["sha256"]:
                raise ValueError("Reference integrity failure: " + str(target.relative_to(root)))
            count += 1
    ref = root / "specs/reference_v1_0"
    ops, templates = load(ref / "catalogs/operators.json"), load(ref / "catalogs/task_templates.json")
    if len(ops) != 32 or len(templates) != 72:
        raise ValueError("Formal operator/template matrix has changed")
    campaign = load(ref / "configs/campaign.json")
    counts = campaign["expected_counts"]
    if counts["generation_attempts"] != 48 * 5 * 4 * 6 * 2 * 2:
        raise ValueError("Generation matrix mismatch")
    if counts["total_execution_attempts"] != 61440:
        raise ValueError("Execution matrix mismatch")
    return {"status": "BOOT_CHECK_PASS", "reference_files_verified": count,
            "operators": len(ops), "templates": len(templates),
            "formal_generation_attempts": counts["generation_attempts"],
            "formal_core_execution_attempts_upper_bound": counts["total_execution_attempts"],
            "full_jsonschema_validation": "SEPARATE_REFERENCE_CHECK", "formal_ready": False,
            "formal_blockers": config["unresolved"]}

def formal_gate(root: Path = ROOT) -> dict:
    report = check(root)
    report["status"] = "BLOCKED_NOT_FROZEN"
    return report
