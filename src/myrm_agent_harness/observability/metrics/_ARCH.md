# metrics/

## Overview
Harness-layer generic metrics utilities for any project using the Myrm framework.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Harness-layer generic metrics utilities for any project using the Myrm framework. | ✅ |
| agent_metrics.py | Core | Harness-layer generic Agent monitoring metrics reusable by any Myrm-based project. | ✅ |
| circuit_breaker_metrics.py | Core | Prometheus metrics for circuit breaker monitoring. | ✅ |
| db_pool_collector.py | Core | Harness-layer generic database connection pool monitor reusable by any Myrm-based project. | ✅ |
| event_log_metrics.py | Core | Framework-level metrics; myrm-agent-server / UIs can scrape the same myrm_ series. | ✅ |
| goal_metrics.py | Core | Goal lifecycle Prometheus metrics — 6 counters (created/completed/budget_limited/paused/cancelled/resumed) + 3 histograms (duration/tokens/cost). Recorded by GoalManager at state transitions. | ✅ |
| llm_metrics.py | Core | Harness-layer generic LLM monitoring metrics reusable by any Myrm-based project. | ✅ |
| registry.py | Core | Provides standard, built-in metrics collection for the Agent framework. | ✅ |
| security_metrics.py | Core | Security and policy enforcement metrics, including policy denial tracking. | ✅ |
