# RCWG agent working agreement

Read `PROJECT_STATE.md`, `docs/START_HERE_zh.md`, `docs/API_ENV_AMENDMENT.md`, and `docs/SPEC_AUDIT.md` before editing.

## Scope and evidence
- Work on a dedicated branch such as `rcwg/boot-001`. Preserve existing user changes and main history.
- Implement and test the current ticket. Preserve the formal 6-model-slot / 32-operator / 72-template / 960-test-case research design.
- Keep `specs/reference_v1_0/` and `prompts/v1_1/` byte-identical. Propose corrections in new versioned paths with a decision record.
- Label engineering fixtures BOOT_ONLY. Keep model service latency, local computational resources, token counts and monetary costs in separate fields.
- Preserve null for unavailable remote CPU/GPU/VRAM observations. Report failures and timeouts as attempts.
- Maintain `PROJECT_STATE.md` and a verifiable acceptance report. Distinguish assistant sandbox, GitHub CI, user WSL, Docker and real cloud results.

## Safety and approvals
- Read-only system checks and changes inside the repository are allowed for this ticket.
- Obtain owner approval before installing system software, changing WSL/Docker settings or IAM, enabling/billing cloud services, spending model tokens, or deleting cloud artifacts.
- Default to offline/mock. CI uses no API secrets and performs no cloud deployment. Real API probes require local approval flags and the durable reservation ledger.
- Keep credentials, raw experimental outputs, gold and private data outside public Git. The ledger is local admission control, not a billing hard cap.
- Review imported research specifications/prompts with the owner before publishing. License choice remains with the owner.
- Preserve main until review; use one independent BOOT commit or a clearly explained small series. Do not claim a PR exists when a write is rejected.

## Commands
```bash
python3.12 -m unittest discover -s tests -v
python3.12 -m rcwg_boot check
python3.12 -m rcwg_boot smoke
python3.12 -m rcwg_boot api-probe
python3.12 -m rcwg_boot check --formal  # expected exit 2
python3 scripts/check_public_tree.py   # after git add, before commit/push
```

`uv.lock` freezes a zero-third-party-dependency BOOT environment. The optional legacy jsonschema checker is a separate audit tool; any future dependencies need a reviewed lock update. The base container image is a candidate until the target digest is recorded.

## 2026-09-19 delegated research decisions
Read docs/spec001a/SPEC-001_DECISIONS.md and METROLOGY-001.md before SPEC edits.
The owner authorizes routine compatible protocol, metric, implementation and test decisions within the core RCWG research scope; implement and report without repeated per-field approval.
Use dedicated branches and preserve original evidence. Financial/IAM/destructive operations remain separately authorized. Actual formal protocol/primary-estimand changes are explicitly versioned, not silently introduced after viewing test outcomes.
Current checkpoint SPEC-001A includes a LIMITED F1 TaskInput profile and offline metrology reducers. It does not implement a complete WorkIR compiler or the 32 runtime operators. Continue with SPEC-001B before EXEC-001. Report unsupported implementation coverage separately from invalid generated plans.
