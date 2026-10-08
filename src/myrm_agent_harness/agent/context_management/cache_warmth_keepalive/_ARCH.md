# cache_warmth_keepalive/

## Overview

Context Cache Warmth Gauge and Heartbeat Keep-Alive Suite (Item 328).
Provides real-time context cache warmth telemetry, countdown metrics,
differential multi-provider cache matrix, and automated silent 1-token keep-alive probing.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public symbols for Context Cache Warmth Gauge and Keep-Alive Suite. | ✅ |
| `cache_warmth_gauge.py` | Telemetry | Real-time countdown gauge and warmth status machine. | ✅ |
| `cache_warmth_suite.py` | Facade | Unified facade suite orchestrating gauge, matrix, and scheduler. | ✅ |
| `keepalive_scheduler.py` | Governance | Heartbeat probe scheduler with safety thresholds. | ✅ |
| `provider_cache_matrix.py` | Matrix | Multi-provider differential TTL and token economics matrix. | ✅ |
| `warmth_types.py` | Types | Strongly-typed domain models, states, and telemetry contracts. | ✅ |
