# HTTP_TIMEOUT_3 and one independent F2/F3 resumption

This prospective engineering profile keeps REQUEST_4, model/decoding limits,
data, verifier, prior results and all conservative holds unchanged. It is
opt-in at the trusted Windows controller; it is never a WorkIR parameter.

HTTPS connection operations use 20 seconds. G has one 600-second monotonic
HTTP deadline including connection, first byte and all body reads. COUNT
retains 90 seconds. Socket shutdown interrupts slow dribble at the same
absolute deadline; an independent process watchdog covers DNS/library and
authentication hangs. Each G physical call has 720 seconds including its
45-second gcloud token issuance and persistence; COUNT has a 210-second
outer bound. Account preflight precedes the batch. New E calls are refused
under this profile; the legacy E workflow deadline is unchanged.

The process parent does not send. On abnormal child exit it records the
uncertainty and fuses the shared task. Restart reads the durable index and
never resends. TLS verification, no redirects, bounded response size and
credential redaction remain enabled. There are no transport retries. Only
the existing complete-429 capacity retry policy can create a bounded child.

INDEPENDENT_F2_F3_RESUME_1 requires a separate explicit user decision, the
same root and recovery epoch, preserved ledger snapshots and exactly the
two named unresolved holds. It installs once, checks each remaining F2
logical slot's full physical dependency closure and no-attempt/no-reservation
history, and restricts new dispatch to that frozen allowlist. The remaining
scope ceiling and kind counts subtract all consumed F2 holds and attempts;
the original recovery pool does not reset. Old manifests and result rows
remain historical evidence; the scope mapping records the new execution
identity through an append-only recovery receipt.

After all executable F2 slots reach explained terminal states, the one
original independent F3 block may be registered with the same timeout/source
identity. Existing unknown F2 and dependent X slots stay missing in the
original denominators; this does not make F2 complete without missing data.
No F4 continuation is authorized by this isolation decision. Any additional
unknown, abandoned permit or active local call refuses further dispatch.
Local controlled concurrency is one; provider activity remains unobservable.

Controlled tests simulate a first byte at 120 seconds, connect/write failures,
slow chunks, truncated framing, real socket interruption, an outer process
stop, no-resend persistence, cumulative budgets, fixed isolation and F3's
changed scheduling gate. They make no paid service calls. WSL Python 3.12.14
and exact-source CI are separate admissions. This document records engineering
choices, not provider latency guarantees or a proven diagnosis of the proxy.

Formal efficiency and reference metrics remain unadmitted. Private runtime
reports, source/host locks, authorization and raw transport evidence are kept
outside public Git. No new cloud deployment is part of this implementation.
