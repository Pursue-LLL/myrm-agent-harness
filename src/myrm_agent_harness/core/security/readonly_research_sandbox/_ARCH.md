# readonly_research_sandbox/

## Overview

Strict typing applied: No `Any` types allowed. src/myrm_agent_harness/core/security/readonly_research_sandbox/__init__.py [INPUT] .facade, .readonly_lease_manager, .types [OUTPUT] Public API exports for readonly_research_sandbox subsystem Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/readonly_research_sandbox/__init__.py [INPUT] .facade, .readonly_lease_manager, .types [OUTPUT] Public API exports for readonly_research_sandbox subsystem Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified Facade for the Read-Only Autonomous Research Lease: grants, revokes and enforces leases, and counts them — src/myrm_agent_harness/core/security/readonly_research_sandbox/facade.py [INPUT] threading, typing, .readonly_lease_manager, .types [OUTPUT] ReadOnlyResearchSandboxFacade, get_readonly_research_sandbox_facade Unified Facade for the Read-Only Autonomous Research Lease: grants, revokes and enforces leases, and counts them. Strict typing applied: No `Any` types allowed. | ✅ |
| readonly_lease_manager.py | Core | Manages dynamic read-only authority leases for autonomous research sessions, — src/myrm_agent_harness/core/security/readonly_research_sandbox/readonly_lease_manager.py [INPUT] threading, time, uuid, dataclasses, core.security.tool_registry (resolve_safety_metadata), .types (DEFAULT_READ_ONLY_TOOLS, LeaseStatusEnum, ReadOnlyLeaseRecord, ResearchModeEnum) [OUTPUT] ReadOnlyLeaseManager Manages dynamic read-only authority leases for autonomous research sessions, physically stripping write/side-effect capabilities and strictly confining tool dispatch. Default-deny: a tool runs only if it is in the lease's allow-list (``DEFAULT_READ_ONLY_TOOLS`` unless overridden); the denial wording marks registry-destructive tools separately. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Data structures and specifications for the Read-Only Autonomous Research Lease — src/myrm_agent_harness/core/security/readonly_research_sandbox/types.py [INPUT] dataclasses, enum, typing [OUTPUT] DEFAULT_READ_ONLY_TOOLS, ResearchModeEnum, LeaseStatusEnum, ReadOnlyLeaseRecord, ReadOnlyResearchMetrics Data structures and specifications for the Read-Only Autonomous Research Lease. Strict typing applied: No `Any` types allowed. | ✅ |
