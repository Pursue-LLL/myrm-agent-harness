# benchmarks/

## Overview
Standalone benchmark probes for validating runtime and agent performance characteristics without writing report artifacts.

## Active Benchmarks

| File | Role | Description | CI |
|------|------|-------------|-----|
| bench_startup_performance.py | Diagnostic | Agent/toolkit import and startup latency regression gate | Yes |
| bench_boundary_detection.py | Diagnostic | Harness/business boundary detection performance + regression vs `baseline_boundary.json` (scan cost compared per file, so tree growth is not read as a slowdown) | Yes |
| context_archive_benchmark.py | Diagnostic | Context archive hash, gzip, atomic write, schema-v2 restore-map costs | No |
| baseline_boundary.json | Baseline | Saved boundary-detection baseline for `--check-regression` | Yes |

## Key Dependencies

- `myrm_agent_harness.infra`
- `myrm_agent_harness.agent.context_management`
