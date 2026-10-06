# external_providers/

## Overview
Pluggable external memory provider lifecycle and supersedes lineage pack.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module public exports for external memory providers and lineage. | ✅ |
| benchmark_suite.py | Core | 3D benchmark evaluation suite (recall accuracy, lifecycle integrity, latency overhead). | ✅ |
| lineage_manager.py | Core | Supersedes version lineage tracking, scope hard filtering, and atomic cascade deletion. | ✅ |
| models.py | Core | Domain models for evidence, derived observations, 7-stage lifecycle, and scopes. | ✅ |
| protocols.py | Core | Unified 5-stage lifecycle protocol and telemetry DTOs for external memory providers. | ✅ |
| scheduler.py | Core | Single active provider orchestrator with 300ms circuit-breaking and trivial prompt gating. | ✅ |
