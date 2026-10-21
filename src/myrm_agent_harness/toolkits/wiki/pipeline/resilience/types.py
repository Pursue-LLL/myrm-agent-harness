"""Compile resilience types for wiki ingestion queue.

[INPUT]
- typing::Literal (POS: standard library types)

[OUTPUT]
- CompileRunSnapshot: vault-scoped compile worker circuit snapshot
- FailureResolution: the error kind a queue row is failed with and the backoff the worker waits before retrying it

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
    """The error kind a queue row is failed with and the backoff the worker waits before retrying it."""

    error_kind: str
    retry_after_seconds: int = 0
