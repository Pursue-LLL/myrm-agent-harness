# session_handoff/

## Overview

Dual-tier secret gate scanner: storage masking placeholders and pre-publish scan blocking.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Session handoff package, readonly share grants, secret gates, and code line blame package. | ✅ |
| `secret_gate_scanner.py` | Core | Dual-tier secret gate scanner: storage masking placeholders and pre-publish scan blocking. | ✅ |
| `session_blame_indexer.py` | Core | Indexer mapping source code lines back to originating session turns and prompt intents. | ✅ |
| `session_handoff_suite.py` | Core | Suite orchestrating session handoff packaging, readonly sharing, secret gating, and line blame. | ✅ |
| `session_handoff_types.py` | Types | Types for session handoff package, readonly share grant, secret gate, and line blame. | ✅ |
