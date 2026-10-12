# readonly_research_sandbox/

## Overview

Strict typing applied: No `Any` types allowed. src/myrm_agent_harness/core/security/readonly_research_sandbox/__init__.py [INPUT] .ephemeral_cow_overlay, .facade, .readonly_lease_manager, .types [OUTPUT] Public API exports for readonly_research_sandbox subsystem Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/readonly_research_sandbox/__init__.py [INPUT] .ephemeral_cow_overlay, .facade, .readonly_lease_manager, .types [OUTPUT] Public API exports for readonly_research_sandbox subsystem Strict typing applied: No `Any` types allowed. | ✅ |
| ephemeral_cow_overlay.py | Core | Provides immutable workspace baselines and in-memory Copy-on-Write (CoW) overlays — src/myrm_agent_harness/core/security/readonly_research_sandbox/ephemeral_cow_overlay.py [INPUT] hashlib, threading, time, uuid, typing, .types (EphemeralCowFileRecord, WorkspaceSnapshot) [OUTPUT] EphemeralCowOverlay Provides immutable workspace baselines and in-memory Copy-on-Write (CoW) overlays for transient research calculations, guaranteeing 100% zero-pollution workspace purity. Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified Facade for Read-Only Autonomous Research Lease & Immutable Snapshot Sandbox Suite — src/myrm_agent_harness/core/security/readonly_research_sandbox/facade.py [INPUT] threading, typing, .ephemeral_cow_overlay, .readonly_lease_manager, .types [OUTPUT] ReadOnlyResearchSandboxFacade Unified Facade for Read-Only Autonomous Research Lease & Immutable Snapshot Sandbox Suite. Strict typing applied: No `Any` types allowed. | ✅ |
| readonly_lease_manager.py | Core | Manages dynamic read-only authority leases for autonomous research sessions, — src/myrm_agent_harness/core/security/readonly_research_sandbox/readonly_lease_manager.py [INPUT] threading, time, uuid, typing, .types (LeaseStatusEnum, ReadOnlyLeaseRecord, ResearchModeEnum) [OUTPUT] ReadOnlyLeaseManager Manages dynamic read-only authority leases for autonomous research sessions, physically stripping write/side-effect capabilities and strictly confining tool dispatch. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Data structures and specifications for Read-Only Autonomous Research Lease & Immutable Snapshot Sandbox Suite — src/myrm_agent_harness/core/security/readonly_research_sandbox/types.py [INPUT] dataclasses, enum, typing [OUTPUT] ResearchModeEnum, LeaseStatusEnum, ReadOnlyLeaseRecord, WorkspaceSnapshot, EphemeralCowFileRecord, ReadOnlyShieldBadge, ReadOnlyResearchMetrics Data structures and specifications for Read-Only Autonomous Research Lease & Immutable Snapshot Sandbox Suite. Strict typing applied: No `Any` types allowed. | ✅ |
