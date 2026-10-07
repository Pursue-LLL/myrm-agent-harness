"""Active-Turn Live Context Compression and Token Pressure Dashboard Suite.

Provides user-intent /compress slash command detection, real-time microsecond token
pressure evaluation for live HUDs, and lossless anchor-preserving middle state folding.
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
