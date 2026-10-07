"""Active-Turn Live Context Compression and Token Pressure Dashboard Suite.

Provides user-intent /compress slash command detection, real-time microsecond token
pressure evaluation for live HUDs, and lossless anchor-preserving middle state folding.

[INPUT]
- agent.context_management.active_compression.active_compression_types::ActiveCompressionConfig,
  ActiveCompressionResult, CompressTriggerKind, TokenPressureLevel, TokenPressureSnapshot (POS: Type
  definitions for Active-Turn Live Context Compression and Token Pressure Dashboard.)
-
  agent.context_management.active_compression.active_context_compression_engine::ActiveContextCompressionEngine,
  TokenPressureGauge, approximate_tokens_for_message, approximate_tokens_for_messages (POS: Core
  implementation of Active-Turn Live Context Compression Engine.)

[OUTPUT]
- Re-exports: ActiveCompressionConfig, ActiveCompressionResult, ActiveContextCompressionEngine,
  CompressTriggerKind, TokenPressureGauge, TokenPressureLevel, TokenPressureSnapshot,
  approximate_tokens_for_message, approximate_tokens_for_messages

[POS]
Active-Turn Live Context Compression and Token Pressure Dashboard Suite.
"""

from .active_compression_types import (
    ActiveCompressionConfig,
    ActiveCompressionResult,
    CompressTriggerKind,
    TokenPressureLevel,
    TokenPressureSnapshot,
)
from .active_context_compression_engine import (
    ActiveContextCompressionEngine,
    TokenPressureGauge,
    approximate_tokens_for_message,
    approximate_tokens_for_messages,
)

__all__ = [
    "ActiveCompressionConfig",
    "ActiveCompressionResult",
    "ActiveContextCompressionEngine",
    "CompressTriggerKind",
    "TokenPressureGauge",
    "TokenPressureLevel",
    "TokenPressureSnapshot",
    "approximate_tokens_for_message",
    "approximate_tokens_for_messages",
]
