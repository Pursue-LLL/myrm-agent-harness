# core/config/

## Overview
Framework-agnostic configuration types. Provides LLMConfig, CustomModelDef, ModelTier, ToolGatewayConfig, and wire protocol identifiers used by both agent/ and toolkits/ without coupling.

## File & Submodule Index

| File | Role | Description |
|------|------|-------------|
| __init__.py | Package | Re-exports CustomModelDef, LLMConfig, ModelTier, ToolGatewayConfig, infer_model_tier. |
| llm.py | Core | CustomModelDef (dataclass) and LLMConfig (Pydantic BaseModel with from_env classmethod). |
| model_tier.py | Core | ModelTier enum (STRONG/MEDIUM/WEAK) and infer_model_tier() for auto-detecting model capability level from name/metadata. |
| gateway.py | Core | ToolGatewayConfig for external tool gateway connection settings. |
| wire.py | Core | Wire protocol identifiers (`chat_completions`, `responses`, `anthropic_messages`) for LLM HTTP transports. |

## Key Dependencies

- No internal dependencies (foundation layer)
