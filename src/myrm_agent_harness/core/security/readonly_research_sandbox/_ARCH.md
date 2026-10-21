# readonly_research_sandbox/

## Overview

Read-only research lease. While a session holds an active lease, the approval middleware lets only the lease's tools run (`DEFAULT_READ_ONLY_TOOLS` unless the grant overrides them) and denies the rest. A host grants a lease per approval session key and revokes it when the run ends; a revoked lease is forgotten.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API of the lease package. | ✅ |
| facade.py | Core | Process-wide entry: `grant_research_lease`, `get_lease`, `revoke_lease`, `evaluate_tool`, plus counters of grants, revocations and blocked calls. | ✅ |
| readonly_lease_manager.py | Core | Lease lifecycle (grant, lazy expiry, revoke-and-forget) and the default-deny tool check; the denial wording separates registry-destructive tools from merely unlisted ones. | ✅ |
| types.py | Core | `DEFAULT_READ_ONLY_TOOLS`, `ResearchModeEnum`, `LeaseStatusEnum`, `ReadOnlyLeaseRecord`, `ReadOnlyResearchMetrics`. | ✅ |

## Key Dependencies

- `core/security/tool_registry` — safety metadata, used to word the denial of destructive tools.
- Called by `agent/middlewares/approval/batch_processor.py`, which asks `evaluate_tool` before every dispatch.
