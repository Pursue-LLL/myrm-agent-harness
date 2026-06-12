"""Core config — framework-agnostic configuration types.

Provides CustomModelDef, LLMConfig, ModelTier used by both agent/ and toolkits/ without coupling.
"""

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig
from myrm_agent_harness.core.config.llm import CustomModelDef, LLMConfig
from myrm_agent_harness.core.config.model_tier import ModelTier, infer_model_tier

__all__ = ["CustomModelDef", "LLMConfig", "ModelTier", "ToolGatewayConfig", "infer_model_tier"]
