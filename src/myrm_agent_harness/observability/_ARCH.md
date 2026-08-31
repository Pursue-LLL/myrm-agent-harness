# observability/

## Overview
Observability tools for Myrm Agent framework. Provides Prometheus metrics, auth failure detection, active health diagnostics, and request tracing context for log correlation.

**Naming disambiguation** (same word, different packages — do not merge or relocate):

| Path | Responsibility |
|------|----------------|
| **`myrm_agent_harness.observability`** (this package) | Metrics, health probes, ContextVar log tracing |
| `myrm_agent_harness.agent.streaming.broadcast` | Chat tool SSE (`ToolBroadcastBus`) |
| `myrm_agent_harness.infra.pubsub` | Server business SSE (`PubSubBus`) |
| `myrm_agent_harness.infra.tracing` | **OpenTelemetry** distributed tracing (optional `[observability]` extra) |
| `toolkits/*/observability.py` | Per-toolkit business-neutral operation DTOs |

`toolkits/` may depend on this package per [toolkits/_ARCH.md](../toolkits/_ARCH.md) Allowed Dependencies.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Observability tools — auth detection, tracing primitives re-export. | ✅ |
| auth_detector.py | Core | Authentication failure detection for circuit breaker logic. | ✅ |

| Submodule | Description |
|-----------|-------------|
| metrics/ | Generic metrics utilities; Prometheus counters require `[observability]` extra (NoOp fallback otherwise). |
| diagnostics/ | Framework-level self-inspection — health probes (incl. gateway runtime vitals), benchmark probes, and diagnostic protocol. |
| tracing/ | ContextVar-based request tracing (trace_id / session_id) with logging.Filter and JSON formatter. |
| invariants/ | Package-owned runtime invariant assertions and registry service (event pairing, lifecycle, data integrity). |
| friction/ | Zero-LLM agent task friction point telemetry, aggregation, and Eval Lab co-evolution pipeline. |
| economics/ | Token economics telemetry, prompt cache reuse auditing, and single-step cost regression detection. |
| latency/ | Agent turn chain latency decomposition, waterfall visualization models, and wall-clock bottleneck identification. |
| digest/ | Team weekly digest and knowledge compounding newsletter engine (activity aggregation, skill health, Markdown rendering). |
| approval_audit/ | Auto-approval trigger diagnostics, quota usage decoupling (Main vs Reviewer), bounded Top-Offenders aggregation, and 1-click allowlist recommendations. |

## Key Dependencies

- `toolkits` (via diagnostics probes)
