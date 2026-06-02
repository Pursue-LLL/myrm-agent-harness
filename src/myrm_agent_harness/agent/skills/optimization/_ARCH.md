# optimization/

## Overview
Skill Optimization Toolkit

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill Optimization Toolkit | — |
| ab_test.py | Test | A/B test engine. Implements scientific optimization validation with traffic splitting and statistica | ✅ |
| aggregation_in_memory.py | Core | In-memory aggregation implementation. Framework-provided, ready-to-use for local/tauri/dev scenarios | ✅ |
| aggregation_stream.py | Core | EventEmitter-to-Aggregator bridge. Connects the event system with the aggregation layer. | ✅ |
| aggregation_streaming.py | Core | Streaming Skill Quality Aggregator | ✅ |
| aggregation_universal.py | Core | Framework-layer universal aggregator decoupled from business layer via DataSource Protocol. | ✅ |
| alert_integration.py | Core | Framework-layer alert integration for production monitoring. | ✅ |
| anomaly_detector.py | Core | Anomaly detection tool (framework layer). Identifies quality regressions using 3-sigma method. | ✅ |
| auto_optimization_engine.py | Core | Closed-loop automatic optimization engine (framework layer). Core competitive differentiator for aut | ✅ |
| batch_executor.py | Core | Framework-layer batch execution engine for skill optimization. | ✅ |
| comparison_analyzer.py | Core | Comparison analysis tool (framework layer). Supports multi-dimensional comparison: before/after, ver | ✅ |
| config.py | Config | Skill optimization system configuration. Provides flexible config options for A/B testing, monitorin | ✅ |
| cost_calculator.py | Core | LLM cost calculator (framework layer). Auto-calculates LLM invocation costs based on pricing tables. | ✅ |
| dlq.py | Core | Dead Letter Queue with Persistence | ✅ |
| event_adapter.py | Core | EventLog adapter (framework layer). Implements the SkillExecutionProvider protocol for event-driven  | ✅ |
| event_emitter.py | Core | Event system (framework layer). Decouples inter-component notifications via publish-subscribe patter | ✅ |
| file_system_storage.py | Core | File system storage (framework layer). Ready-to-use persistent storage implementation. | ✅ |
| health_check.py | Core | Health check protocol (framework layer). Unified health check interface for all components. | ✅ |
| in_memory_storage.py | Core | In-memory storage (framework layer). Ready-to-use volatile storage implementation. | ✅ |
| insights.py | Core | Insights analysis system (framework layer). Provides deep statistical analysis of skill executions. | ✅ |
| llm_client.py | Core | Generic LLM call wrapper. Implements exponential backoff retry, timeout control, and error handling. | ✅ |
| math_utils.py | Core | Statistical utility functions for skill quality aggregation | ✅ |
| observability.py | Core | Lightweight observability support with zero external dependencies. Provides MetricsCollector, Timer, | ✅ |
| optimizer.py | Core | Skill optimizer core engine. Orchestrates the full optimization pipeline: data collection, analysis, | ✅ |
| predictive_analyzer.py | Core | Predictive analysis tool (framework layer). Forecasts future quality trends based on historical data | ✅ |
| prometheus_metrics.py | Core | Prometheus Metrics for Skill Optimization | ✅ |
| protocols.py | Core | Protocols for Skill Optimization Subsystem | ✅ |
| quality_calculator.py | Core | Quality score calculator. Computes 5-dimension quality scores from raw execution samples. | ✅ |
| rate_limiter.py | Core | Per-User Rate Limiter for Skill Optimization | ✅ |
| recommender.py | Core | Skill optimization recommendation engine (framework layer). Intelligently identifies skills worth op | ✅ |
| result_comparator.py | Core | Shadow test result comparator. Provides accurate result comparison for the observation feedback loop | — |
| scheduler.py | Core | Optimization scheduler (framework layer). Automates the skill optimization workflow. | ✅ |
| security.py | Core | Multi-layer skill security validator. Prevents malicious code in LLM-generated skills. | ✅ |
| types.py | Config | Skill optimization system core type definitions. Provides type-safe data structures and protocol int | ✅ |

## Key Dependencies

- `backends`
- `observability`
- `toolkits`
