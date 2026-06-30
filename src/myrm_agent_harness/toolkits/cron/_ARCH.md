# cron/

## Overview
Cron toolkit entry point. Aggregates scheduling engine, CRUD manager, protocols, built-in
stores, triggers, delivery, runners, and situation report aggregator. **Single SSOT for
user-facing automation** (time-based schedules plus **three wired** event triggers:
event / system_event / webhook via `triggers.py`; `poll` and `manual` are reserved
enum values not yet attached to `TriggerConfig`. Product wiring in
`myrm-agent-server/app/core/cron/`). Supports `skip_if_active`
concurrency control, `PreFlightCondition` script injection (probe interceptor), `context_from`
cross-task data piping (inject referenced jobs' latest successful output), incremental monitoring
(`MonitorConfig` — set/hash/timeseries change detection via `infra.incremental`), and
`SituationReportBuilder` for enriching heartbeat prompts with dynamic context from registered data sources.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Cron toolkit entry point. Aggregates scheduling engine, CRUD manager, protocols, built-in | ✅ |
| cron_agent_tools.py | Core | Agent tool for scheduled task management. Supports blueprint-based creation, incremental monitoring (`monitor_type`/`monitor_enabled`), context chaining (`context_from`), and active hours. | ✅ |
| delivery.py | Core | Built-in webhook ResultDelivery for cron job results. | ✅ |
| delivery_guard.py | Core | Exact-token `[SILENT]` detection for delivery filtering (`is_silent_output`). | ✅ |
| heartbeat.py | Core | Heartbeat — convenience layer over CronManager for periodic agent self-checks. Supports both INTERVAL and CRON scheduling (time-of-day triggers). | ✅ |
| manager.py | Core | Cron CRUD orchestration layer. Validates job configurations, persists changes via CronStore, | ✅ |
| protocols.py | Core | Protocols for the cron toolkit. | ✅ |
| runners.py | Core | Built-in job runners (ShellJobRunner, RouterJobRunner). | ✅ |
| situation.py | Core | Situation Report — pluggable context aggregator for heartbeat ticks. SituationSection Protocol + SituationReportBuilder (concurrent build, token budget, fault-tolerant) + SituationContext. | ✅ |
| stores.py | Core | Built-in in-memory CronStore for development and testing. | ✅ |
| triggers.py | Core | Trigger type definitions and security helpers. | ✅ |
| types.py | Config | Cron job domain types. JobResult supports `skipped` + `skip_reason` for runner-level skip signalling. | ✅ |

| Submodule | Description |
|-----------|-------------|
| engine/ | Cron scheduling engine internals. |

## Key Dependencies

- `core`
- `infra`
