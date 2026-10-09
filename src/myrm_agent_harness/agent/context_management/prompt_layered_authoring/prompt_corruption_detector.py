"""Prompt corruption and cross-layer boundary leakage detector.

[INPUT]
- layered_types: PromptLayerType, CorruptionSeverity, PromptCorruptionIssue,
  LayeredPromptDraft, LayeredAuthoringConfig.

[OUTPUT]
- PromptCorruptionDetector: Analyzes layered drafts to flag selective blindness risks,
  rule bloat, and workflows that should be offloaded to independent skills.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.prompt_layered_authoring
- Module: prompt_corruption_detector.py
"""

import re
from typing import List, Sequence
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.layered_types import (
    CorruptionSeverity,
    LayeredAuthoringConfig,
    LayeredPromptDraft,
    PromptCorruptionIssue,
    PromptLayerType,
)


class PromptCorruptionDetector:
    """Detects prompt rot, boundary leakage, and complex workflows that should become skills."""

    _STEP_MARKERS = re.compile(
        r"(?:^\s*(?:step\s*\d+|第\s*\d+\s*步|\d+\.|\bfirst\b|\bthen\b|\bnext\b|\bfinally\b))",
        re.IGNORECASE | re.MULTILINE,
    )

    _STYLE_BUZZWORDS = (
        "be polite",
        "be friendly",
        "show enthusiasm",
        "say hello",
        "friendly tone",
        "热情",
        "客气",
        "问候",
    )

    _PROHIBITION_MARKERS = (
        "never",
        "do not",
        "strictly forbid",
        "forbidden",
        "must not",
        "严禁",
        "禁止",
        "绝不",
    )

    def __init__(self, config: LayeredAuthoringConfig) -> None:
        self._config = config

    def analyze_draft(self, draft: LayeredPromptDraft) -> Sequence[PromptCorruptionIssue]:
        """Performs comprehensive architectural inspection across the three authoring layers.

        Args:
            draft: The user prompt draft divided into the three layers.

        Returns:
            A sequence of detected PromptCorruptionIssue instances.
        """
        issues: List[PromptCorruptionIssue] = []

        # 1. Inspect Hard Rules Layer
        issues.extend(self._inspect_hard_rules(draft.hard_rules))

        # 2. Inspect Workflow Routing Layer
        issues.extend(self._inspect_workflow_routing(draft.workflow_routing))

        # 3. Inspect Narrative Style Layer
        issues.extend(self._inspect_narrative_style(draft.narrative_style))

        return tuple(issues)

    def _inspect_hard_rules(self, text: str) -> List[PromptCorruptionIssue]:
        issues: List[PromptCorruptionIssue] = []
        if not text.strip():
            return issues

        # Check character limit
        if len(text) > self._config.max_hard_rules_chars:
            issues.append(
                PromptCorruptionIssue(
                    layer=PromptLayerType.HARD_RULES,
                    severity=CorruptionSeverity.WARNING,
                    message=(
                        f"Hard rules length ({len(text)} chars) exceeds recommended limit "
                        f"({self._config.max_hard_rules_chars} chars). High risk of model selective blindness."
                    ),
                    suggested_fix="Condense hard rules into concise negative constraints; move workflows to skills.",
                )
            )

        # Detect accidental polite filler or conversational style instructions in hard rules
        for buzz in self._STYLE_BUZZWORDS:
            if buzz in text.lower():
                issues.append(
                    PromptCorruptionIssue(
                        layer=PromptLayerType.HARD_RULES,
                        severity=CorruptionSeverity.INFO,
                        message=f"Hard rules contain conversational style keyword '{buzz}'.",
                        suggested_fix="Relocate tone and conversational guidelines to the Narrative Style layer.",
                    )
                )
                break

        return issues

    def _inspect_workflow_routing(self, text: str) -> List[PromptCorruptionIssue]:
        issues: List[PromptCorruptionIssue] = []
        if not text.strip():
            return issues

        # Count procedural step indicators
        matches = self._STEP_MARKERS.findall(text)
        step_count = len(matches)
        threshold = self._config.workflow_step_limit_before_skill_recommendation

        if step_count > threshold:
            issues.append(
                PromptCorruptionIssue(
                    layer=PromptLayerType.WORKFLOW_ROUTING,
                    severity=CorruptionSeverity.WARNING,
                    message=(
                        f"Workflow layer contains {step_count} procedural steps, exceeding threshold ({threshold}). "
                        "Inline execution flows rot quickly and inflate system prompt token overhead."
                    ),
                    suggested_fix=(
                        "Offload this multi-step operational procedure into a dedicated Skill package "
                        "(e.g., skill_name/SKILL.md) instead of keeping it in the system prompt."
                    ),
                    suggest_skill_offload=True,
                )
            )

        # Check for absolute prohibitions that belong in Hard Rules
        for marker in self._PROHIBITION_MARKERS:
            if marker in text.lower():
                issues.append(
                    PromptCorruptionIssue(
                        layer=PromptLayerType.WORKFLOW_ROUTING,
                        severity=CorruptionSeverity.INFO,
                        message=f"Workflow routing contains hard prohibition marker '{marker}'.",
                        suggested_fix="Elevate non-negotiable invariant constraints to the Hard Rules layer.",
                    )
                )
                break

        return issues

    def _inspect_narrative_style(self, text: str) -> List[PromptCorruptionIssue]:
        issues: List[PromptCorruptionIssue] = []
        if not text.strip():
            return issues

        # Detect accidental system permissions or commands in style layer
        for marker in self._PROHIBITION_MARKERS:
            if marker in text.lower():
                issues.append(
                    PromptCorruptionIssue(
                        layer=PromptLayerType.NARRATIVE_STYLE,
                        severity=CorruptionSeverity.WARNING,
                        message=f"Narrative style layer contains hard rule constraint '{marker}'.",
                        suggested_fix="Move invariant behavioral constraints to the Hard Rules layer.",
                    )
                )
                break

        return issues
