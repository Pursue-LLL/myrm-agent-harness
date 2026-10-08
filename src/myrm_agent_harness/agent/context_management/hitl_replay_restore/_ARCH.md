# hitl_replay_restore/

## Overview

End-to-end suite orchestrating selective reconnect passive replay analysis, ordinary tool side-effect suppression, and pending human-in-the-loop restoration.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Reconnect passive replay filtering and human-in-the-loop restoration package. | ✅ |
| `hitl_replay_restore_engine.py` | Core | Engine orchestrating selective passive replay scanning and interactive HITL resolution. | ✅ |
| `hitl_replay_restore_suite.py` | Core | Unified orchestration facade for reconnect passive replay filtering and HITL restoration. | ✅ |
| `hitl_replay_types.py` | Types | Domain contracts for reconnect passive replay and selective HITL restoration. | ✅ |
| `passive_replay_scanner.py` | Core | Scanner performing selective replay analysis to isolate pending HITL calls from ordinary tools. | ✅ |
