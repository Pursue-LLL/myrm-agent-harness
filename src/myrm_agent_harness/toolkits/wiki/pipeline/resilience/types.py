"""Compile resilience types for wiki ingestion queue.

[INPUT]
typing::Literal (POS: standard library types)

[OUTPUT]
CompileRunSnapshot: vault-scoped compile worker circuit snapshot
FailureResolution: per-item retry/pause policy result

[POS]
Wiki compile resilience types. DTOs shared by queue, compiler, and server API mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CompileCircuitState = Literal["running", "paused"]
CompilePhase = Literal["idle", "structure_survey", "semantic_compile", "postprocess"]


@dataclass(frozen=True, slots=True)
class CompileRunSnapshot:
    """Vault-scoped compile worker circuit snapshot for API/UI."""

    state: CompileCircuitState
    pause_reason: str = ""
    primary_error_kind: str = ""
    phase: CompilePhase = "idle"
    facet_count: int = 0
    warning_count: int = 0
    survey_skipped: bool = False


@dataclass(frozen=True, slots=True)
class FailureResolution:
    """Resolved failure policy for a single queue item."""

    error_kind: str
    retryable: bool
    counts_toward_pause: bool
    retry_after_seconds: int = 0
