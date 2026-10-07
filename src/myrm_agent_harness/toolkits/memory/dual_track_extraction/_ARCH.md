# dual_track_extraction/

## Overview
Dual-Track Memory Extraction Routing & Anti-Silent-Drop Gateway: dual-track classification (declarative facts vs procedural rules), automatic dispatch to ProceduralMemory, and transparent destiny reports defending against silent drop defects.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade of the dual track extraction subsystem. | ✅ |
| `classifier.py` | Core | Classifies incoming text into Fact, Procedural Rule, Dual-Track, or No-Signal. | ✅ |
| `gateway.py` | Core | Adaptive extraction and routing gateway defending against silent drop defects. | ✅ |
| `types.py` | Types | Typed data contracts for the dual track extraction subsystem. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
