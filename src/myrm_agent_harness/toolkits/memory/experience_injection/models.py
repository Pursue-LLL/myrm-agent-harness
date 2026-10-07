# [POS]: src/myrm_agent_harness/toolkits/memory/experience_injection/models.py
# [INPUT]: myrm_agent_harness.toolkits.memory.procedure_experience.models (ProcedureMemoryEntry)
# [OUTPUT]: ExperienceCallSite, InjectionStatus, ExperienceInjectionConfig, ExperienceInjectionResult

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from myrm_agent_harness.toolkits.memory.procedure_experience.models import (
    ProcedureMemoryEntry,
)


class ExperienceCallSite(StrEnum):
    """Specific precise call sites for experience injection (aligned with OpenViking PR #2007)."""

    SKILL_LOAD = "skill_load"
    SUBAGENT_SPAWN = "subagent_spawn"
    PRE_WRITE = "pre_write"


class InjectionStatus(StrEnum):
    """Outcome status of an experience injection evaluation."""

    INJECTED = "injected"
    SKIPPED_DISABLED = "skipped_disabled"
    SKIPPED_ALREADY_INJECTED = "skipped_already_injected"
    SKIPPED_NO_MATCH = "skipped_no_match"
    SKIPPED_TIMEOUT = "skipped_timeout"


@dataclass(frozen=True)
class ExperienceInjectionConfig:
    """Dual-gating and threshold configuration for experience injection."""

    agent_memory_enabled: bool = True
    exp_write_tools_enabled: bool = True
    max_experiences_per_site: int = 2
    monitored_write_tools: tuple[str, ...] = (
        "write_file",
        "edit_file",
        "replace_file_content",
        "write_to_file",
        "apply_patch",
    )
    timeout_ms: float = 50.0


@dataclass(frozen=True)
class ExperienceInjectionResult:
    """Immutable result payload detailing the outcome of an injection attempt."""

    call_site: ExperienceCallSite
    status: InjectionStatus
    injected_entries: tuple[ProcedureMemoryEntry, ...] = field(default_factory=tuple)
    enriched_content: str = ""
    rollback_required: bool = False
    injected_ids: tuple[str, ...] = field(default_factory=tuple)
