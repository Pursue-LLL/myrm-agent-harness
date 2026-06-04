# benchmarks/

## Overview
Standalone benchmark probes for validating runtime and agent performance characteristics without writing report artifacts.

## Active Benchmarks

| File | Role | Description | CI |
|------|------|-------------|-----|
| bench_startup_performance.py | Diagnostic | Agent/toolkit import and startup latency regression gate | Yes |
| bench_boundary_detection.py | Diagnostic | Harness/business boundary detection performance + regression vs `baseline_boundary.json` | Yes |
| bench_batch_performance.py | Diagnostic | Message delivery queue batch throughput (documented in ARCHITECTURE.md) | No |
| context_archive_benchmark.py | Diagnostic | Context archive hash, gzip, atomic write, schema-v2 restore-map costs | No |
| baseline_boundary.json | Baseline | Saved boundary-detection baseline for `--check-regression` | Yes |

## Archive

One-off optimization and skill-search evaluation scripts are in `archive/`. See [archive/_ARCH.md](archive/_ARCH.md).

## Key Dependencies

- `myrm_agent_harness.infra`
- `myrm_agent_harness.agent.context_management`
