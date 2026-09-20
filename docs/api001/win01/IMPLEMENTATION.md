# API-001 WIN-01 implementation

WIN-01 supersedes NET-01 and the previous WSL-only / mandatory impersonation route. Reviewed baseline e9571b1f9aac872fe050a1d901b1e3318c93e276 is retained; PR5 remains draft. Formal readiness stays false.

Configuration v2 explicitly binds GCLOUD_USER, USER, approved principal, project/quota, Windows backend and hashes of the native Python executable, gcloud.cmd and deployed standalone helper. V1 SA behavior remains unchanged. Approval v2 binds the new manifest plus both WSL and native Windows acceptance hashes. No old acceptance hash authorizes new source.

The Windows launcher invokes WSL Python 3.12.14. Linux retains the original supervisor and all 98 runtime pins. The bridge invokes an existing Windows Python with isolated flags and fixed argv. The standalone helper obtains its own user token and sends HTTPS through the verified Windows loopback proxy with certificate/hostname validation. Tokens never cross to Linux or enter files. Effective auth/TLS/proxy settings are checked natively; no global setting is changed.

Pipe protocol 1 rejects duplicate keys, invalid UTF-8/BOM, nonfinite values, excess bytes, unknown fields/methods, path/shell injection, missing reservations and mismatched hashes. Raw request and response bytes use canonical base64 without JSON rewriting. The helper emits a bound dispatch marker before HTTP. A killed or truncated pipe without a marker records unknown dispatch and retains its reservation. There is no automatic model retry, redirect, repair, regeneration or fallback.

A Linux exclusive preparation claim and one ticket-wide SQLite ledger under runs/ prevent resetting the approved allowance by changing output directories. All reservations commit before helper dispatch. Windows HTTP and WSL pipe durations use separate monotonic clock scopes; neither changes F1 kernel metrology. Local admission is not a billing hard cap; invoice cost and provider internal resources remain unavailable unless independently supplied.

Validation entry points:

- scripts/accept_api001.py: original 821 IDs + new Linux regressions, original 17 test-source pins plus the reviewed binding-test file, full EXEC gate, 27 sentinels, six mutants, runtime pins, supervised mock P0/P1.
- scripts/windows/accept_api001_windows.py: actual Windows 3.13.4 offline helper tests, native PID/runtime/Chinese paths/deployment bytes. No cloud credentials or network are used by tests.
- scripts/accept_api001_windows_integration.py: actual Windows fake-wire processes to WSL original supervisor, correct and omitted-filter negative plans, P0/P1 both preserved. Its separate fake executable is never selectable by LIVE.
- rcwg_api.live_review: mode-aware read-only re-opening of sealed LIVE observations, credentials, response receipts, original bytes, execution/verifier evidence. Model answer PASS is independent of transport/F1 completion.

Native Windows private deployment uses an inspected protected ACL. Unix chmod is not asserted to establish Windows ACL. Source, deployed helper and test harness hashes accompany private acceptance. Linux CI is reported separately and is not represented as Windows login evidence.

Cloud history and final LIVE state are in the private delivery, not inferred from source comments. CR-01 / CR-02 were separately authorized by the owner for three precise API enables; no explicit IAM roles, billing bindings or runner were created by these commands. Unknown provider-managed side effects and credential refresh HTTP counts are not assigned zero.
