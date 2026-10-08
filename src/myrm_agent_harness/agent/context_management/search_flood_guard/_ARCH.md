# search_flood_guard

Architecture and module inventory for the `search_flood_guard` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting search flood guard types, sliding window tracker, progressive soft-cap gate, and facade suite |
| `flood_guard_types.py` | Domain models and contracts for multi-agent per-context search flood guard and progressive soft-cap |
| `per_agent_sliding_window_tracker.py` | Per-agent-context sliding window tracker managing timestamp queues and LRU eviction |
| `progressive_soft_cap_gate.py` | Progressive soft-cap gate making flow control decisions and tapering search results |
| `multi_agent_search_flood_guard_suite.py` | Unified facade suite coordinating isolated per-agent sliding windows, progressive soft-capping, and hard circuit-breaker cooldowns |
