# config/

## Overview
Agent configuration package — unified export of all config types and utilities.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent configuration package — unified export of all config types and utilities. | — |
| docs_generator.py | Core | Configuration documentation generator. Auto-generates config reference docs by reflecting Pydantic s | ✅ |
| exceptions.py | Core | Framework-level exception definitions. Business layer can inherit these | ✅ |
| file_io.py | Core | File I/O configuration. Defines resource limits (concurrent reads, file size caps), regex safety (Re | ✅ |
| llm.py | Core | Agent configuration layer. Re-exports CustomModelDef/LLMConfig from core.config.llm (SSoT) and defines agent-specific AgentConfig, StorageConfig, TracingConfig. | ✅ |
| llm_safety.py | Core | Provider safety layer. Prevents API errors from invalid tool calls and dirty conversation history. | ✅ |
| litellm_routing.py | Core | LiteLLM 路由表、`normalize_env_model_selection_string`、前端常量生成数据源 | ✅ |
| parsers.py | Core | `to_litellm_model` 组合 litellm_routing 前缀规则 | ✅ |
| presets.py | Core | Configuration presets layer. Provides best-practice configuration presets for common scenarios. | ✅ |
| readiness.py | Core | Framework-level readiness check infrastructure. Business layer inherits to implement | ✅ |
| validator.py | Core | Configuration validation layer. Checks config validity, consistency, and security, producing structu | ✅ |

## Key Dependencies

- `core.config` (CustomModelDef, LLMConfig — Single Source of Truth)
- `backends`
- `toolkits`
- `utils`
