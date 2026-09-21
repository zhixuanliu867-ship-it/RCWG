# FULL001 implementation decisions

The authoritative scope is RCWG-FULL-001/1.0.0, recorded in SPEC_IDENTITY.json.
This document records implementation choices, not experimental observations.

1. Work starts at 2824ee8e7678a39b3bff2ac701ffececd50d1e81 in an isolated
   rcwg/full-001 worktree. The original N4 worktree and its evidence remain intact.
2. COMPAT1 copies the small orchestration and structural-validation modules into
   a versioned package, reuses legacy type, expression, public-task and operator
   validation, and adds explicit dispatch for the supplemental forms. No global
   monkeypatching or change to old profile acceptance is permitted.
3. Parameter binding remains a dependency even if a node does not otherwise
   consume its source. Static type witnesses are internal to validation; actual
   bound values and ranges are checked in the worker. Shape, service identity,
   authority, storage and paths cannot be supplied by a value binding.
4. WSL has the target Python 3.12.14 but no C++ compiler. Native builds will use
   existing CI compilers. No system installer, live model/count request or host
   calibration is authorized by this decision.
5. All six completion states start false. Each requirement remains pending until
   its complete scope has actual evidence. Partial tests never pass a larger gate.
