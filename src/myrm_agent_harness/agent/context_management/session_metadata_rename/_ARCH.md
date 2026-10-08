# session_metadata_rename/

## Overview

End-to-end suite orchestrating authoritative session display rename mutations via metadata.name and deterministic precedence arbitration.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Session display renaming via metadata.name and title precedence arbitration package. | ✅ |
| `metadata_name_resolver.py` | Core | Precedence resolver and title normalizer for session display naming. | ✅ |
| `metadata_rename_types.py` | Types | Domain contracts for session display rename and metadata-name precedence resolution. | ✅ |
| `session_metadata_rename_engine.py` | Core | Core mutation and storage engine for session display renaming via metadata.name. | ✅ |
| `session_metadata_rename_suite.py` | Core | End-to-end orchestration facade for session metadata display renaming and precedence arbitration. | ✅ |
