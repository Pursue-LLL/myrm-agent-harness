# cron/

## Overview
Cron toolkit entry point. Aggregates scheduling engine, CRUD manager, protocols, built-in
stores, triggers, delivery, runners, and situation report aggregator. **Single SSOT for
user-facing automation** (time-based schedules plus **five wired** event triggers:
event / system_event / webhook / poll / stream via `triggers.py`; `manual` is a reserved
enum value not yet attached to `TriggerConfig`. Product wiring in
`myrm-agent-server/app/core/cron/`). Supports `skip_if_active`
concurrency control, `PreFlightCondition` script injection (probe interceptor), `context_from`
cross-task data piping (inject referenced jobs' latest successful output), incremental monitoring
(`MonitorConfig` — set/hash change detection via `infra.incremental`), and
`SituationReportBuilder` for enriching heartbeat prompts with dynamic context from registered data sources.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Cron toolkit entry point. Aggregates scheduling engine, CRUD manager, protocols, built-in | ✅ |
| cron_agent_tools.py | Core | Agent tool for scheduled task management. Blueprint catalog via `action=blueprints` (not Turn1 schema injection). Supports `default_delivery`, `reminder` jobs, cron-execution mutating guard, incremental monitoring, context chaining, active hours. **`required_capabilities` / `tools_allowed` CSV params** on add/update; `BlueprintFiller` 5-tuple includes caps + tools. | ✅ |
| delivery.py | Core | Built-in webhook ResultDelivery for cron job results. | ✅ |
| delivery_guard.py | Core | Exact-token `[SILENT]` detection for delivery filtering (`is_silent_output`). | ✅ |
| heartbeat.py | Core | Heartbeat — convenience layer over CronManager for periodic agent self-checks. Supports both INTERVAL and CRON scheduling (time-of-day triggers). Optional `agent_id` binding to inherit Agent Profile (model, prompt, skills). | ✅ |
| manager.py | Core | Cron CRUD orchestration layer. Validates job configurations, persists changes via CronStore, | ✅ |
| protocols.py | Core | Protocols for the cron toolkit. | ✅ |
| runners.py | Core | Built-in job runners (ShellJobRunner, RouterJobRunner, NotificationRunner). | ✅ |
| situation.py | Core | Situation Report — pluggable context aggregator for heartbeat ticks. SituationSection Protocol + SituationReportBuilder (concurrent build, token budget, fault-tolerant) + SituationContext. | ✅ |
| stores.py | Core | Built-in in-memory CronStore for development and testing. | ✅ |
| triggers.py | Core | Trigger type definitions and security helpers. | ✅ |
| types.py | Config | Cron job domain types. `JobType.REMINDER` for zero-LLM prompt delivery. JobResult supports `skipped` + `skip_reason`. **`CronJob.required_capabilities` + `CronJob.tools_allowed`**; `CronJobPatch` supports `clear_tools_allowed`. | ✅ |

| Submodule | Description |
|-----------|-------------|
| engine/ | Cron scheduling engine internals. |

## Key Dependencies

- `core`
- `infra`
