# WorkIR public contract — CLOUD001 v1 / PROTO_PATCH_AUDIT_F01

Return one plain JSON object, without fences, prose, code, or repair instructions.
The public TASK remains authoritative; a logical plan cannot replace its requirements.
The supplied development example is shared material, not an answer to the current task.
No verification recipe, gold rows, result artifact or verification feedback is supplied.

WorkIR 1.0 requires ir_version, task_id, external_inputs, nodes, result. Optional
root fields are assumptions and limits. task_id must match the public TASK exactly.
external_inputs maps a local alias to an existing TASK dataset ID, for example
{"records":"dataset:records:v1"}. This mapping declares an input; it is not itself
a node reference. A root scan input uses "$input.records", NOT "records", NOT
"source_dataset", and NOT the raw dataset ID. Alias names follow
[a-z][a-z0-9_]{0,47}. The dataset ID must already appear in the public TASK.

Root references are "$input.alias" or "node_id.output_port". Both node and port
must exist in the same lexical scope. A bare identifier is not a reference.
The result field references an existing node output, for example "answer.result".
Each node requires id, operator, implementation, inputs, params, outputs.
Input-port keys and output-port keys must match the approved operator contract.
outputs maps ports to declared types (e.g. Stream[Record], Table, Result);
declarations must agree with actual inferred producer/consumer types and schema.
The supplied schema, approved operator worklist, catalog and example describe the
parameters and port contracts. Their original historical implementation labels
do not override the actual engineering runtime profile below.

Optional node fields are after, resources, storage, regions. after contains unique
same-scope node IDs. Edges from inputs, after and region bindings must be acyclic.
resources supports cpu_slots, max_parallelism, batch_rows as positive integers;
cpu_slots cannot exceed TASK.resources.cpu_slots. Storage values are stream,
memory, disk, shared_ref. Declared limits do not establish observed budget success.
The compiler admits at most 48 total logical nodes, depth 2 for regions,
max_node_instances <= 4096 and max_loop_iterations <= 16.

General static region grammar (not executable in this F1 root-chain profile):
map owns body; branch owns then and else; loop owns body. Each region has explicit
bindings, nodes, yield. Binding RHS references are resolved in the parent scope.
Inside a region use "$bound.alias" or same-scope "node.port", not "$input.alias"
or an implicit outer-node reference. Only map/body bindings may use "$item";
only loop/body bindings may use "$state". Region yields must match declared
output ports. These rules do not imply arbitrary regions are implemented at runtime.

This CLOUD001 engineering run uses the unchanged F1 serial root-chain Python
reference executor: scan/sequential; filter/scalar or vectorized;
top_k/full_sort or streaming_heap; project/column_view or copy;
emit/json_artifact. No region or arbitrary DAG execution is available here.
Use only public dataset IDs, fields, output contract and resource conditions.
An inefficient but legal algorithm is not invalid merely because it is inefficient.
Formal isolation and benchmark comparability have not been established.
