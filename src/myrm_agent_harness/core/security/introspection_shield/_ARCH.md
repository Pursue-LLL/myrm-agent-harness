# introspection_shield/

## Overview

Exports for Agent Runtime Introspection Shield & Decoupled Workspace Template Suite. src/myrm_agent_harness/core/security/introspection_shield/__init__.py [INPUT] facade, types, blackhole_policy, workspace_hydrator [OUTPUT] Public API exports Exports for Agent Runtime Introspection Shield & Decoupled Workspace Template Suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports for Agent Runtime Introspection Shield & Decoupled Workspace Template Suite — src/myrm_agent_harness/core/security/introspection_shield/__init__.py [INPUT] facade, types, blackhole_policy, workspace_hydrator [OUTPUT] Public API exports Exports for Agent Runtime Introspection Shield & Decoupled Workspace Template Suite. | ✅ |
| blackhole_policy.py | Core | Implements blackhole path containment and fake-root redirection for sandbox runtime introspection shielding — src/myrm_agent_harness/core/security/introspection_shield/blackhole_policy.py [INPUT] fnmatch, logging, pathlib, time, typing [OUTPUT] IntrospectionBlackholePolicy Implements blackhole path containment and fake-root redirection for sandbox runtime introspection shielding. Blocks snooping into host paths, container entrypoints, framework source code, and host configuration. Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified facade orchestrating sandbox introspection blackhole protection, — src/myrm_agent_harness/core/security/introspection_shield/facade.py [INPUT] pathlib, typing [OUTPUT] IntrospectionShieldSuite Unified facade orchestrating sandbox introspection blackhole protection, fake-root redirection, and decoupled workspace template hydration. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Data structures and specifications for Agent Runtime Introspection Shield & Decoupled Workspace Template Suite — src/myrm_agent_harness/core/security/introspection_shield/types.py [INPUT] dataclasses, enum, typing [OUTPUT] IntrospectionProbeType, DecoupledTemplateStandard, ShieldActionEnum, ProbeEvaluationResult, HydratedTemplateRecord, IntrospectionShieldMetrics Data structures and specifications for Agent Runtime Introspection Shield & Decoupled Workspace Template Suite. Strict typing applied: No `Any` types allowed. | ✅ |
| workspace_hydrator.py | Core | Implements adaptive hydration and scaffolding for open standards workspace template files: — src/myrm_agent_harness/core/security/introspection_shield/workspace_hydrator.py [INPUT] logging, pathlib, typing [OUTPUT] DecoupledWorkspaceHydrator Implements adaptive hydration and scaffolding for open standards workspace template files: SOUL.md, USER.md, IDENTITY.md, BOOTSTRAP.md, HEARTBEAT.md. Strict typing applied: No `Any` types allowed. | ✅ |
