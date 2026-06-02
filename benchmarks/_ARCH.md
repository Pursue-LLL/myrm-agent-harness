# benchmarks/

## Overview
Standalone benchmark probes for validating runtime and agent performance characteristics without writing report artifacts.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| context_archive_benchmark.py | Diagnostic | Measures context archive hash, gzip, atomic write, schema-v2 restore-map write, reuse validation, restore guidance, and CacheTtlPrune large-payload prune costs across text/JSON/unicode payload samples, including estimator snapshots, with JSON-only stdout and optional threshold enforcement for regression gates. | ✅ |

## Key Dependencies

- `myrm_agent_harness.infra`
- `myrm_agent_harness.agent.context_management`
