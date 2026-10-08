# spawn_reservation/

## Overview

End-to-end suite orchestrating spawn name reservation until durable admission.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Spawn name reservation until durable admission package. | ✅ |
| `reservation_types.py` | Types | Strongly typed contracts for spawn name reservation and admission durability. | ✅ |
| `spawn_admission_suite.py` | Core | End-to-end suite orchestrating spawn name reservation until durable admission. | ✅ |
| `spawn_name_reservation_engine.py` | Core | Concurrent thread-safe engine managing spawn name reservations until durable admission. | ✅ |
