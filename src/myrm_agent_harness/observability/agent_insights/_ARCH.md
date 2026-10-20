# agent_insights/

## Overview
Custom Agent Insights and Operational Observability Suite.
Eliminates the black-box syndrome of deployed autonomous agents by aggregating three critical operational dimensions (aligned with Notion 3.7 Custom Agent Insights API):
1. **Intent & Scenario Clusters**: Top user business jobs-to-be-done and request distributions.
2. **Skill Health & Latency Funnel**: Per-skill call volume, success rates, P95 latencies, and top failure root causes.
3. **HITL Bottlenecks & Token ROI**: Approval delay friction and deliverables produced per token spent.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public exports for CustomAgentInsightsTracker, metrics, and snapshots. | ✅ |
| `models.py` | DTO & Enums | Immutable data models for intent clusters, skill health funnels, and HITL metrics. | ✅ |
| `tracker.py` | Core Tracker | Thread-safe in-memory aggregator recording per-agent telemetry and computing windowed snapshots. | ✅ |

## Design Constraints & Principles
1. **Per-Agent Dimensionality**: Telemetry is indexed by `agent_id` allowing granular drill-downs for customized agents.
2. **Time-Window Filtering**: Supports 7-day and 30-day operational windows.
3. **Thread Safety**: High-concurrency agent interactions safely update in-memory counters under lock.
4. **Strict Typing**: Zero `Any` usage across all schemas and tracker methods.
