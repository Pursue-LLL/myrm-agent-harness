# evidence_disclosure/

## Overview

Isomorphic evidence disclosure subsystem providing canonical action details shared between active turns and completed history, deterministic query scope isolation, and real-reading offset pagination.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Evidence disclosure subsystem package entry point and facade exports. | ✅ |
| `active_evidence_disclosure_suite.py` | Core | Comprehensive facade suite managing isomorphic disclosure, scopes, and pagination. | ✅ |
| `evidence_disclosure_types.py` | Types | Domain contracts and types for isomorphic active and history disclosure. | ✅ |
| `evidence_pagination_reader.py` | Core | Pagination reader binding evidence viewing to verified real-reading offsets. | ✅ |
| `evidence_query_locator.py` | Core | Deterministic query locator and scope isolator for active and completed evidence. | ✅ |
