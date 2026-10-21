"""
[INPUT]: Submodule exports for active skill context propagation and span telemetry processing.
[OUTPUT]: Unified package facade for active_skill_telemetry.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/active_skill_telemetry/__init__.py
"""

from .context import (
    bind_active_skill,
    get_active_skill,
    reset_active_skill,
    set_active_skill,
)
from .models import (
    ActiveSkillTelemetryReport,
    SkillSpanRecord,
    SkillTelemetryAggregation,
)
from .processor import (
    ACTIVE_SKILL_ATTRIBUTE_KEY,
    COMPAT_SKILL_ATTRIBUTE_KEY,
    ActiveSkillSpanProcessor,
)

__all__ = [
    "bind_active_skill",
    "get_active_skill",
    "set_active_skill",
    "reset_active_skill",
    "SkillSpanRecord",
    "SkillTelemetryAggregation",
    "ActiveSkillTelemetryReport",
    "ACTIVE_SKILL_ATTRIBUTE_KEY",
    "COMPAT_SKILL_ATTRIBUTE_KEY",
    "ActiveSkillSpanProcessor",
]
