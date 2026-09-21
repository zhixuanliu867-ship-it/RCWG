# FULL001 isolated dependencies

Python target: 3.12.14. requirements.lock is generated with hashes from the
explicit requirements.in pins; runtime commands never install dependencies.
The legacy root pyproject.toml and uv.lock remain unchanged. Native C++20
builds link the same pinned Arrow distribution used by Python through its
documented C++ Python bridge. Build manifests record compiler, flags, source,
Python SOABI, shared libraries and actual extension hashes.

Dependency preparation is a separate, explicit repository-local operation.
System packages, service changes and real host calibration are not included.
