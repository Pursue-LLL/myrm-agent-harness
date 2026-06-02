# core/config/

## Overview
Framework-agnostic configuration types. Provides LLMConfig and CustomModelDef used by both agent/ and toolkits/ without coupling.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports LLMConfig. | ✅ |
| llm.py | Core | CustomModelDef (dataclass) and LLMConfig (Pydantic BaseModel with from_env classmethod). | ✅ |

## Key Dependencies

- No internal dependencies (foundation layer)
