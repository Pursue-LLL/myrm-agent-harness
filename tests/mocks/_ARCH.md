# tests/mocks/

## Overview

Shared in-memory test doubles for backend Protocol implementations. Not part of the distributable package.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Re-exports `InMemorySkillBackend`, `InMemoryStorageBackend` |
| `llm_wire_server.py` | Mock | Loopback fake LLM provider (`FakeProviderServer`) with OpenAI-chat and Anthropic-messages response builders, so tests assert the exact JSON body a real LiteLLM call puts on the wire without network access |
| `skill_backend.py` | Mock | In-memory `SkillBackend` for skill unit tests |
| `storage_backend.py` | Mock | In-memory `StorageProvider` for storage unit tests |

## Consumers

- `tests/backends/test_skills.py`
- `tests/toolkits/storage/test_storage.py`
- `tests/toolkits/llms/core/test_output_budget_wire.py`
