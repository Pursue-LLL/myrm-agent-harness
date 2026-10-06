# config/

## Overview
Agent configuration package — unified export of all config types and utilities.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent configuration package — unified export of all config types and utilities. | — |
| exceptions.py | Core | Framework-level exception definitions. Business layer can inherit these | ✅ |
| file_io.py | Core | File I/O configuration. Defines resource limits (concurrent reads, file size caps), compiler-grade read output caps (max_chars/max_lines/max_line_length), regex safety (Re | ✅ |
| llm.py | Core | Agent configuration layer. Re-exports CustomModelDef/LLMConfig from core.config.llm (SSoT) and defines agent-specific AgentConfig, StorageConfig, TracingConfig. | ✅ |
| llm_safety.py | Core | Provider safety normalization for LLM calls made outside the middleware chain (summary prefix, grace call). `normalize_messages()` is the production pair `sanitize_tool_history()` → `repair_dangling_tool_calls()`; a well-formed history is returned unchanged. | ✅ |
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
