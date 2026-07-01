"""Planner Configuration

Configuration options for the planner tool.

[INPUT]
- (none)

[OUTPUT]
- SkillSummary: Minimal skill info for Planner awareness (avoids coupling...
- PlannerConfig: Planner configuration

[POS]
Planner Configuration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SkillSummary:
    """Minimal skill info for Planner awareness (avoids coupling to full SkillMetadata)."""

    name: str
    description: str


@dataclass
class PlannerConfig:
    """Planner configuration

    Customize planner behavior including prompts, storage, and protocol settings.

    Example:
        >>> config = PlannerConfig(
        ...     storage_prefix="/my_planner",
        ...     enable_3_strike=True,
        ...     max_retry_count=3,
        ...     output_format="markdown",
        ... )
    """

    # Storage configuration
    storage_prefix: str = "/planner"
    """Storage path prefix for plan files"""

    # Additional storage prefixes scanned when locating an existing persisted plan.
    legacy_storage_prefixes: tuple[str, ...] = ("planner_",)

    # Prompt configuration
    system_prompt: str | None = None
    """Custom system prompt (overrides default)"""

    update_prompt: str | None = None
    """Custom update prompt template (overrides default)"""

    # Feature configuration
    enable_3_strike: bool = True
    """Enable 3-Strike Protocol for error handling"""

    max_retry_count: int = 3
    """Maximum retry count before escalating to user"""

    enable_shadow_sync: bool = True
    """Enable shadow sync (save plan in multiple formats)"""

    # Output configuration
    output_format: Literal["line", "markdown", "json"] = "line"
    """Default output format for planner tool"""

    # Behavior configuration
    auto_advance: bool = True
    """Auto-advance to next step when current step completed"""

    strict_dependencies: bool = True
    """Enforce strict dependency checking"""

    # Skill awareness
    available_skills: list[SkillSummary] = field(default_factory=list)
    """Skills the Planner can reference when decomposing tasks.
    Injected into the system prompt so the LLM knows which skills exist."""


__all__ = ["PlannerConfig", "SkillSummary"]
