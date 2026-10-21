# survival/

Instance survival monitoring — memory pressure hooks, resource sampling, startup timing.

| File | Role |
| --- | --- |
| `__init__.py` | Package entrypoint |
| `memory_pressure.py` | Global memory pressure coordination |
| `resource_monitor.py` | High-fidelity resource monitor |
| `startup.py` | Application startup performance toolkit |
| `desktop_memory_watchdog.py` | Core | Desktop memory watchdog with multi-level idle compaction. | ✅ |
| `desktop_watchdog_types.py` | Core | Domain types for desktop long-session eviction and memory watchdog suite. | ✅ |
| `rolling_archive.py` | Core | Long-session automatic rolling archive engine. | ✅ |
| `session_dehydration.py` | Core | Session context and rich media offscreen dehydration engine. | ✅ |
