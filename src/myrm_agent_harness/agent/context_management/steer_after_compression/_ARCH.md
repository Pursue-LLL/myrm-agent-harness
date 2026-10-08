# steer_after_compression/

## Overview

End-to-end suite orchestrating active worker steering across context compaction and out-of-band message sanitization.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Post-compaction worker steering and out-of-band message sanitization package. | ✅ |
| `active_worker_steer_resolver.py` | Core | Core resolution and dispatch engine for steering active workers after context compaction. | ✅ |
| `oob_message_sanitizer.py` | Core | Sanitization engine filtering out-of-band management messages from replay contexts. | ✅ |
| `steer_after_compression_suite.py` | Core | Unified orchestration facade for post-compaction steering and out-of-band context sanitization. | ✅ |
| `steer_compression_types.py` | Types | Domain contracts for post-compaction steering and out-of-band message sanitization. | ✅ |
