"""Wiki compile resilience: failure policy, circuit pause, display sanitization.

[POS]
See module docstring.
"""

from .circuit import CompileCircuitStore
from .failure_policy import (
    EMBED_WINDOW_VIOLATION,
    IO_MISSING,
    evaluate_batch_pause,
    is_transient_error_kind,
    resolve_embed_failure,
    resolve_io_failure,
    resolve_llm_failure,
)
from .sanitize import sanitize_display_message
from .types import CompilePhase, CompileRunSnapshot, FailureResolution

__all__ = [
    "EMBED_WINDOW_VIOLATION",
    "IO_MISSING",
    "CompileCircuitStore",
    "CompilePhase",
    "CompileRunSnapshot",
    "FailureResolution",
    "evaluate_batch_pause",
    "is_transient_error_kind",
    "resolve_embed_failure",
    "resolve_io_failure",
    "resolve_llm_failure",
    "sanitize_display_message",
]
