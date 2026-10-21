# active_skill_telemetry/

## Overview
Active skill telemetry processor propagating `myrm.skill.active` attributes across OpenTelemetry execution spans.
Inspired by Omnigent PR #9547 and commit `14b70a2411` to bind the currently active skill via ContextVar and ensure all downstream model, tool, and subprocess spans carry the active skill dimension for granular cost attribution, latency percentile aggregation, and failure triage.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public re-exports of models, context functions, and ActiveSkillSpanProcessor. | ✅ |
| `models.py` | Domain Models | Pydantic schemas for SkillSpanRecord, SkillTelemetryAggregation, and ActiveSkillTelemetryReport. | ✅ |
| `context.py` | ContextVar Manager | Async-safe ContextVar binding for active skill lifecycle management and token restoration. | ✅ |
| `processor.py` | Core Processor | ActiveSkillSpanProcessor injecting attributes onto spans and computing P95 latency aggregations per skill. | ✅ |
