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

## Active follow-on: SPEC-001B

Read `docs/spec001b/DECISIONS.md`, `CODEX_TASK.md`, `ACCEPTANCE.md` and `A_REVIEW.md`.
A reviewed baseline has 131 tests. This starter adds 63 foundation tests (194 total).
The foundation is intentionally incomplete as a full compiler; never promote its
`STRUCTURE_PASS` to `IR_VALIDATED` without the remaining typed/parameter checks.
Scientific scope and formal gates remain unchanged. Do not change source fixtures
or expected sentinel outcomes to conceal implementation failures.

## EXEC-001 当前票
完整目标与权限见 docs/exec001/CODEX_TASK.md、DECISIONS.md、ACCEPTANCE.md。只完成参考脚本不能宣称X00-X15完成。受测源码必须覆盖rcwg_exec和worker/verifier。合并授权只限明确审过的PR2/3 SHA，使用match-head，不绕过CI。F1 reference计量scope保留，不自动升级formal。


## Active ticket: RCWG-NATIVE-001

Current scope: docs/native001/START_HERE_zh.md and SCOPE.json. N0–N3 combined; historical text above retained. One independent branch and one draft stacked PR; no merges, no model/cloud/system/cgroup changes. formal_ready=false.


## Active ticket: RCWG-NATIVE-001 / N4

Base 456a30d0d242ec005bfb9e25fdc7a45c72aa9af8; branch rcwg/native-001-n4. Read docs/native001n4/START_HERE_zh.md and DECISIONS.md. Offline counter hardening, receipt-bound finite calibration implementation and independent regression gates. One draft stacked on rcwg/native-001; PR6/7 not merged. Host proposal remains approved=false; real calibration NOT_RUN pending exact owner receipt. No models/count/GCP/IAM/install/cgroup writes. Formal BLOCKED_NOT_FROZEN. Historical evidence above retained.
