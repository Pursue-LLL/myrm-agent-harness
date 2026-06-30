# core/

## Overview
Framework-agnostic foundation layer. Provides security, config, events, hooks, artifacts, and feature flags capabilities shared by both `agent/` and `toolkits/`, eliminating coupling between them.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Core layer entry — module docstring only, no re-exports at this level. | — |
| context_vars.py | Core | Cross-layer ContextVar registry shared by agent/ and toolkits/ without coupling. | ✅ |

| Submodule | Description |
|-----------|-------------|
| security/ | Security primitives — PII detection, content boundary, prompt injection guard, SSRF guard, audit, path security, execution policy, credential vault (label→password/TOTP for tool injection). |
| config/ | Framework-agnostic configuration types — LLMConfig, CustomModelDef. |
| events/ | Event type definitions — AgentEventType, AgentStreamEvent, THINKING_TAG_NAMES. |
| hooks/ | Hook lifecycle definitions — HookEvent, HookDefinition variants, HookResult, event payloads. |
| artifacts/ | Artifact type constants — ArtifactType enum, extension/MIME mappings, inference utilities. |
| features/ | Feature Flags — registration, lifecycle management, runtime querying. |

## Key Dependencies

- No internal dependencies (foundation layer — depended upon by agent/ and toolkits/)
