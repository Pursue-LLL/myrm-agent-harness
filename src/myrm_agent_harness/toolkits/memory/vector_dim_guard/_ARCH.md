# vector_dim_guard/

## Overview

Vector index dimension guard and task-based rebuild orchestration suite. Provides automatic dimension mismatch detection, non-destructive index recreation (preserving underlying documents without dropping data), task execution locks, and real-time progress event streaming with failed item tracking.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Facade export for vector dimension guard and rebuild orchestrator. | ✅ |
| `models.py` | Types | Domain models for dimension inspection, rebuild phases, progress events, and failed items. | ✅ |
| `guard.py` | Core | Vector dimension guard inspecting dimensionality and enforcing non-destructive rebuilds. | ✅ |
| `orchestrator.py` | Core | Rebuild task orchestrator with mutex locks, multi-phase progress, and failed items list. | ✅ |
