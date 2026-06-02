"""Core config — framework-agnostic configuration types.

Provides CustomModelDef and LLMConfig used by both agent/ and toolkits/ without coupling.
"""

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig
from myrm_agent_harness.core.config.llm import CustomModelDef, LLMConfig

__all__ = ["CustomModelDef", "LLMConfig", "ToolGatewayConfig"]
