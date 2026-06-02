# quality/

## Overview
Tool quality monitoring for evolution system.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Tool quality monitoring for evolution system. | — |
| fallback.py | Core | Tool fallback mechanism. Sub-second automatic switching (<3s), smart execution order (last_success f | ✅ |
| monitor.py | Core | Tool quality monitor core. Provides 3-dimension degradation detection (success + latency + error) wi | ✅ |
