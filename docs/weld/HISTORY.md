# From RCWG to WELD

RCWG began with typed workflow generation, controlled operators, and executable contracts for graph-centered tasks. The early repository implemented transport, static validation, and a reference execution path. Its specifications and code remain in the repository as historical artifacts.

The research then separated a measurement benchmark from a broader hypothesis about architectural judgment. WELD is the measurement study. It asks how a model's evolving workflow affects work, realized time benefit, and maintenance after changes.

Graph-centered operators were expanded into five native domains. Runtime node creation, revisions, artifact versions, task-level validation, and full request accounting made cross-scenario execution observable. An initially difficult pilot was followed by a 100-parent easy/medium main suite to create an adequate population of valid comparisons while preserving design choices.

The final study uses ten API-served models, 6,000 stages, and 8,874 response-fixed native executions. The public WELD release exposes its papers, result tables, task cards, and measured source. The old 6-model-slot/32-operator/72-template design belongs to the preserved RCWG specifications; it is not the matrix used in the WELD paper.

The repository was renamed from `RCWG` to `WELD` with its Git history retained. Original reference specifications and prompt versions remain unchanged. The current reading entry point is the root README and `docs/weld/`.
