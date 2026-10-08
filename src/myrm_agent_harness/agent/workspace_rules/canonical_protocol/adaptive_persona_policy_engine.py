# [INPUT]: ActorVoiceMode, RelationshipMaturityStage, RuntimeVibe
# [OUTPUT]: AdaptivePersonaPolicy, AdaptivePersonaPolicyEngine
# [POS]: agent/workspace_rules/canonical_protocol/adaptive_persona_policy_engine.py

"""Dynamic adaptive persona policy engine evolving relationship maturity and arbitrating real-talk voice.

[INPUT]
- RelationshipMaturityStage, RuntimeVibe, ActorVoiceMode: Policy enums.

[OUTPUT]
- AdaptivePersonaPolicy: Resolved active policy configuration.
- AdaptivePersonaPolicyEngine: Evaluates relationship maturity stage, input vibes, and critical incident voice overrides.

[POS]
Policy evolution layer in canonical workspace protocol subsystem breaking 2025 static persona limitations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from .canonical_types import (
    ActorVoiceMode,
    RelationshipMaturityStage,
    RuntimeVibe,
)


@dataclass(frozen=True)
class AdaptivePersonaPolicy:
    """Active runtime behavioral policy guiding model tone and verbosity."""

    stage: RelationshipMaturityStage
    vibe: RuntimeVibe
    voice_mode: ActorVoiceMode
    policy_instruction: str


class AdaptivePersonaPolicyEngine:
    """Evolves persona behavior across collaboration days and arbitrates transparent Real-Talk overrides."""

    CRITICAL_INCIDENT_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(?:database corrupt|data loss|security breach|unauthorized|fatal error|kernel panic)", re.IGNORECASE),
        re.compile(r"(?:rm -rf|drop database|delete customer|purge all|破坏性|安全红线|资金风险)", re.IGNORECASE),
        re.compile(r"(?:permission denied|access revoked|circuit breaker open|emergency stop)", re.IGNORECASE),
    )

    def determine_maturity_stage(self, collaboration_days: int) -> RelationshipMaturityStage:
        """Derive collaboration maturity stage from cumulative interaction days."""
        if collaboration_days <= 1:
            return RelationshipMaturityStage.DAY_1_ONBOARDING
        if collaboration_days < 30:
            return RelationshipMaturityStage.DAY_7_COLLABORATIVE
        return RelationshipMaturityStage.DAY_40_VETERAN_SYNERGY

    def detect_runtime_vibe(self, user_query: str) -> RuntimeVibe:
        """Infer conversational vibe from user input rhythm and urgency cues."""
        q = user_query.strip()
        # Incident or urgent flags
        if any(p.search(q) for p in self.CRITICAL_INCIDENT_PATTERNS):
            return RuntimeVibe.URGENT_INCIDENT

        # Concise command: short text, starting with imperatives
        words = q.split()
        if len(words) <= 8 and (q.endswith("!") or any(q.lower().startswith(p) for p in ("run", "fix", "deploy", "build", "cat", "git"))):
            return RuntimeVibe.CONCISE_COMMAND

        # Exploratory thinking: interrogatives or architectural keywords
        if any(kw in q.lower() for kw in ("how should we", "architect", "tradeoff", "compare", "why", "how to design", "探讨", "方案对比")):
            return RuntimeVibe.EXPLORATORY_THINKING

        return RuntimeVibe.CONCISE_COMMAND

    def evaluate_voice_mode(self, user_query: str, system_incident: bool = False) -> ActorVoiceMode:
        """Arbitrate between in-character persona and objective Real-Talk engineer mode."""
        if system_incident:
            return ActorVoiceMode.REAL_TALK

        if any(p.search(user_query) for p in self.CRITICAL_INCIDENT_PATTERNS):
            return ActorVoiceMode.REAL_TALK

        return ActorVoiceMode.IN_CHARACTER

    def synthesize_policy(
        self,
        collaboration_days: int = 1,
        user_query: str = "",
        system_incident: bool = False,
    ) -> AdaptivePersonaPolicy:
        """Compute the effective behavioral policy instruction for prompt injection."""
        stage = self.determine_maturity_stage(collaboration_days)
        vibe = self.detect_runtime_vibe(user_query) if user_query else RuntimeVibe.CONCISE_COMMAND
        voice = self.evaluate_voice_mode(user_query, system_incident=system_incident)

        lines: list[str] = ["### 🧭 [Dynamic Behavioral Policy]"]

        # Voice Mode Arbitration (Highest Priority)
        if voice == ActorVoiceMode.REAL_TALK:
            lines.append(
                "- 🚨 [VOICE: REAL-TALK ACTIVE]: Critical safety boundary or system anomaly detected. "
                "Completely drop persona embellishments or playful tone. "
                "Communicate with transparent, objective engineer rigor."
            )
        else:
            lines.append("- [VOICE: IN-CHARACTER]: Express full personality nuances and distinctive tone.")

        # Maturity Stage Guidance
        if stage == RelationshipMaturityStage.DAY_1_ONBOARDING:
            lines.append(
                "- [STAGE: DAY-1 ONBOARDING]: Maintain humble etiquette, explicitly clarify ambiguous parameters, "
                "and explain steps clearly before taking major actions."
            )
        elif stage == RelationshipMaturityStage.DAY_40_VETERAN_SYNERGY:
            lines.append(
                "- [STAGE: DAY-40 VETERAN SYNERGY]: Zero-Fluff military brevity. Understand user shorthand and abbreviations. "
                "Directly execute routine low-risk actions without repetitive confirmations."
            )
        else:
            lines.append("- [STAGE: COLLABORATIVE]: Balanced engineering rhythm with proactive recommendations.")

        # Vibe Regulation
        if vibe == RuntimeVibe.CONCISE_COMMAND:
            lines.append("- [VIBE: CONCISE]: Prioritize immediate commands, code diffs, and rapid turnaround.")
        elif vibe == RuntimeVibe.EXPLORATORY_THINKING:
            lines.append("- [VIBE: EXPLORATORY]: Elaborate architectural trade-offs, options, and structured pros/cons.")

        policy_text = "\n".join(lines)
        return AdaptivePersonaPolicy(
            stage=stage,
            vibe=vibe,
            voice_mode=voice,
            policy_instruction=policy_text,
        )
