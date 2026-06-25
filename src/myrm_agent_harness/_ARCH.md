# myrm_agent_harness/

## Overview
Myrm Agent Harness — a production-grade framework for building, deploying, and managing AI agents with skill systems, context management, security, and observability.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Core | Package entry — lazy re-exports via api/ | — |
| api/ | Core | Public API surface for external consumers (factory, Protocol, DTO) |
| _distribution.py | Core | Source vs compiled mode; version + platform key validation |
| _runtime_platform.py | Core | Runtime platform key detection (shared with build tooling) |
| _core_ip_manifest.py | Core | Generated core IP import paths (from core_manifest.yaml) |
| _verify_distribution.py | Core | Post-install verify CLI (`verify-harness-distribution`) |

| Submodule | Description |
|-----------|-------------|
| core/ | Framework-agnostic foundation layer — security, config, events, hooks, artifacts, features. Used by both agent/ and toolkits/. |
| agent/ | Agent core module — runtime, context management, skill system. External consumers use api/ instead. |
| backends/ | Backend implementations — skill backends and storage adapters. |
| client.py | SDK facade — AgentClient providing clean, fluent API to configure and run Agent. |
| eval/ | Eval Framework — Agent behavior quality evaluation. |
| infra/ | Infrastructure layer — file locks, message delivery, tracing, state monitoring. |
| observability/ | Observability tools — Prometheus metrics, auth detection, health diagnostics. |
| runtime/ | Agent runtime infrastructure for single-instance execution. |
| toolkits/ | Generic, framework-agnostic toolkit collection (like lodash). MUST NOT depend on agent/. |
| utils/ | Utility library — error handling, logging, text processing, token tracking, URL tools. |

## Key Dependencies

- No internal dependencies (top-level package entry point)
