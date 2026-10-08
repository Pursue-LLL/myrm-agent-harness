# context_health_dashboard

Architecture and module inventory for the `context_health_dashboard` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting context health types, gauge, auto-purge sentry, doctor probe, and facade suite |
| `context_health_types.py` | Domain models, capacity watermarks, savings metrics, and diagnostic receipts |
| `realtime_health_gauge.py` | Realtime context capacity meter, headroom calculator, and tool hotspot aggregator |
| `ephemeral_auto_purge_sentry.py` | Disk hygiene sentry scanning and purging session-isolated caches and temporary SQLite databases |
| `context_health_doctor_probe.py` | Non-destructive diagnostic probe inspecting SQLite FTS5 capabilities and write permissions |
| `realtime_context_health_suite.py` | Top-level unified facade orchestrating context health evaluation, auto-purge sentry, and environment doctor |
