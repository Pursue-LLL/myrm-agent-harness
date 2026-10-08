# local_prefill_guard/

## Overview
Local LLM long-context prefill latency guard and adaptive pruning scheduler subsystem (Item 317).

Solves the critical bottleneck where local models on high-memory hardware (e.g. 128GB/256GB Mac Studio) suffer from catastrophic prefill stalls (such as 64k TTFT reaching 118s) by providing:
1. **Local Endpoint Latency & TTFT Estimator**: Introspects endpoint identifiers (Ollama, vLLM, MLX, llama.cpp, LM Studio) and models quadratic attention + linear FFN polynomial complexity to predict prefill stalls and latency warning tiers.
2. **Local-Adaptive Aggressive Pruning Engine**: Dynamically shifts pruning thresholds from standard 2048 down to 512 tokens (and 256 in emergency) when accumulated context threatens local hardware, replacing consumed large tool results with compact finding summaries.
3. **WebUI Streaming Prefill Capsule**: Generates transparent prefill progress capsules and fast-trim recommendations for frontend UI and streaming clients.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for local LLM prefill guard and adaptive pruning. | — |
| local_prefill_types.py | Models | Strongly-typed contracts (`LocalEndpointKind`, `LatencyWarningLevel`, `PruningPolicyTier`, `LocalEndpointProfile`, `PrefillLatencyEstimate`, `AdaptivePruningDecision`, `PrefillProgressCapsule`, `PrunedResultSummary`, `LocalPrefillGuardResult`). | ✅ |
| endpoint_inspector_and_ttft_estimator.py | Core | Endpoint introspection and polynomial TTFT prefill latency estimator. | ✅ |
| adaptive_pruning_scheduler.py | Core | Dynamic pruning threshold calculation and deterministic message pruning engine. | ✅ |
| local_prefill_guard_suite.py | Facade | High-level facade orchestrating inspection, TTFT estimation, adaptive pruning, and progress capsule generation. | ✅ |

## Key Dependencies

- `agent.context_management` — Context management and token estimation pipeline
- `langchain_core.messages` — LangChain message protocols
