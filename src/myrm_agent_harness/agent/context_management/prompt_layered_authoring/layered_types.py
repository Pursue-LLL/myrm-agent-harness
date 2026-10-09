"""Types and data contracts for three-layered prompt authoring and narrative style presets.

[INPUT]
- None (pure type definitions and immutable data contracts).

[OUTPUT]
- Exports enumerations and dataclasses for prompt layer types, style presets,
  corruption issues, layered drafts, and assembled system prompt results.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.prompt_layered_authoring
- Module: layered_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Sequence


class PromptLayerType(str, Enum):
    """The three discrete architectural layers of a structured agent system prompt."""

    HARD_RULES = "hard_rules"
    WORKFLOW_ROUTING = "workflow_routing"
    NARRATIVE_STYLE = "narrative_style"


class NarrativeStylePreset(str, Enum):
    """Standardized narrative communication presets grounded in production experience."""

    NATURAL_PROSE = "natural_prose"
    CONCISE_EXECUTIVE = "concise_executive"
    ENGINEERING_RIGOROUS = "engineering_rigorous"
    WARM_CHARISMATIC = "warm_charismatic"
    CUSTOM = "custom"


class CorruptionSeverity(str, Enum):
    """Severity of prompt rot or cross-layer contamination."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class PromptCorruptionIssue:
    """Diagnostic issue identifying prompt rot, bloat, or blurred boundaries."""

    layer: PromptLayerType
    severity: CorruptionSeverity
    message: str
    suggested_fix: str
    suggest_skill_offload: bool = False


@dataclass(frozen=True)
class LayeredPromptDraft:
    """User authoring draft split cleanly across the three foundational layers."""

    hard_rules: str = ""
    workflow_routing: str = ""
    narrative_style: str = ""
    selected_preset: NarrativeStylePreset = NarrativeStylePreset.NATURAL_PROSE
    custom_style_notes: str = ""


@dataclass(frozen=True)
class AssembledPromptResult:
    """The structured assembly outcome containing diagnostic findings."""

    assembled_system_prompt: str
    detected_issues: Sequence[PromptCorruptionIssue] = field(default_factory=tuple)
    is_valid: bool = True
    total_characters: int = 0
    layer_character_counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class LayeredAuthoringConfig:
    """Configuration rules and thresholds for authoring guardrails."""

    max_hard_rules_chars: int = 2500
    max_workflow_chars: int = 2000
    max_style_chars: int = 1500
    workflow_step_limit_before_skill_recommendation: int = 4
    enforce_strict_separation: bool = False
