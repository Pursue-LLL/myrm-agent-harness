"""[INPUT] types, sanitizer, protocol submodules.
[OUTPUT] Facade exports for Subagent Bounded Structured Failure Facts & Privacy-Preserving Diagnostic Protocol.
[POS] Public interface for subagent failure facts subsystem.
"""

from __future__ import annotations

from .protocol import SubagentDiagnosticProtocol
from .sanitizer import MAX_DIAGNOSTIC_FACTS_BYTES, SafeFailureSanitizer
from .types import (
    RemediationAction,
    StructuredFailureFact,
    SubagentFailureCategory,
    SubagentFailureStage,
)

__all__ = [
    "MAX_DIAGNOSTIC_FACTS_BYTES",
    "RemediationAction",
    "SafeFailureSanitizer",
    "StructuredFailureFact",
    "SubagentDiagnosticProtocol",
    "SubagentFailureCategory",
    "SubagentFailureStage",
]
