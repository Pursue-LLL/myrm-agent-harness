"""Skill semantic modifiers parser and audience adapter runtime.

Parses natural language modifiers (e.g. "ELI5", "executive", "in-depth", "rigorous")
from slash commands or prompt inputs and produces non-invasive audience cognitive patches.

[INPUT]
- str: raw prompt command or modifier arguments

[OUTPUT]
- AudienceProfile: target audience specification
- SkillModifierResult: structured parsed modifiers and audience instruction patch
- parse_skill_modifiers: extractor function

[POS]
myrm-agent-harness/src/myrm_agent_harness/backends/skills/runtime_modifiers.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re


class AudienceDepth(StrEnum):
    ELI5 = "eli5"  # Explain like I'm 5 (plain terms, vivid analogies, no jargon)
    EXECUTIVE = "executive"  # Executive brief (conclusion first, ROI/KPI focus, bulleted actions)
    SENIOR = "senior"  # Hardcore engineering / domain expert (high density, deep technical rigor)
    STANDARD = "standard"  # Default balanced output


@dataclass(frozen=True, slots=True)
class AudienceProfile:
    depth: AudienceDepth
    tone_directives: tuple[str, ...]
    forbidden_tropes: tuple[str, ...]
    output_instructions: str


_AUDIENCE_PROFILES: dict[AudienceDepth, AudienceProfile] = {
    AudienceDepth.ELI5: AudienceProfile(
        depth=AudienceDepth.ELI5,
        tone_directives=(
            "Explain using intuitive, everyday real-world analogies (e.g. kitchens, cars, traffic).",
            "Keep sentences short and simple. Strictly avoid dense acronyms without immediate translation.",
            "Focus on the 'why it matters' feeling rather than abstract mathematical mechanics.",
        ),
        forbidden_tropes=(
            "Do NOT use unexplained enterprise buzzwords or theoretical jargon.",
            "Do NOT paste raw code snippets unless specifically asked for toy examples.",
        ),
        output_instructions=(
            "\n\n[AUDIENCE COGNITIVE PATCH: ELI5 MODE]\n"
            "- Target Audience: Complete beginner / 5-year-old mindset.\n"
            "- Tone: Warm, visual, zero jargon, intuitive analogies first.\n"
            "- Constraint: Prohibit textbook definitions; explain concepts through vivid storytelling."
        ),
    ),
    AudienceDepth.EXECUTIVE: AudienceProfile(
        depth=AudienceDepth.EXECUTIVE,
        tone_directives=(
            "Bottom-Line-Up-Front (BLUF): State the core business impact and recommendation in the first 2 sentences.",
            "Quantify trade-offs in terms of ROI, delivery timelines, operational risks, and headcount cost.",
            "Use clear decision matrix tables and bulleted action checklists.",
        ),
        forbidden_tropes=(
            "Do NOT delve into implementation minutiae or line-by-line code walk-throughs.",
            "Do NOT write rambling narrative paragraphs.",
        ),
        output_instructions=(
            "\n\n[AUDIENCE COGNITIVE PATCH: EXECUTIVE BRIEFING]\n"
            "- Target Audience: C-Level / VP / Board stakeholders.\n"
            "- Tone: Crisp, assertive, metrics-driven, decisive.\n"
            "- Format: 1) Executive Summary & Recommendation, 2) Cost/Risk/ROI Impact, 3) Next Action Checklist."
        ),
    ),
    AudienceDepth.SENIOR: AudienceProfile(
        depth=AudienceDepth.SENIOR,
        tone_directives=(
            "High information density. Directly cite technical specifications, protocols, and architectural trade-offs.",
            "Evaluate time/space complexity, distributed systems edge cases, and failure domain boundaries.",
            "Provide production-ready code with exhaustive error-handling and typing.",
        ),
        forbidden_tropes=(
            "Do NOT provide elementary 101 explanations or boilerplate textbook definitions.",
            "Do NOT omit edge-case failure modes or concurrency pitfalls.",
        ),
        output_instructions=(
            "\n\n[AUDIENCE COGNITIVE PATCH: SENIOR SPECIALIST]\n"
            "- Target Audience: Staff/Principal Engineers and subject-matter experts.\n"
            "- Tone: Precise, rigorous, zero hand-waving, evidence-backed.\n"
            "- Depth: Address distributed edge cases, concurrency locks, observability, and strict types."
        ),
    ),
    AudienceDepth.STANDARD: AudienceProfile(
        depth=AudienceDepth.STANDARD,
        tone_directives=(),
        forbidden_tropes=(),
        output_instructions="",
    ),
}

_MODIFIER_ALIASES: dict[str, AudienceDepth] = {
    "eli5": AudienceDepth.ELI5,
    "小白": AudienceDepth.ELI5,
    "通俗": AudienceDepth.ELI5,
    "科普": AudienceDepth.ELI5,
    "beginner": AudienceDepth.ELI5,
    "executive": AudienceDepth.EXECUTIVE,
    "高管": AudienceDepth.EXECUTIVE,
    "汇报": AudienceDepth.EXECUTIVE,
    "领导": AudienceDepth.EXECUTIVE,
    "brief": AudienceDepth.EXECUTIVE,
    "senior": AudienceDepth.SENIOR,
    "专家": AudienceDepth.SENIOR,
    "硬核": AudienceDepth.SENIOR,
    "深度": AudienceDepth.SENIOR,
    "hardcore": AudienceDepth.SENIOR,
}


@dataclass(frozen=True, slots=True)
class SkillModifierResult:
    clean_command: str
    audience_depth: AudienceDepth
    profile: AudienceProfile
    modifiers: tuple[str, ...]

    def apply_to_prompt(self, base_prompt: str) -> str:
        """Append non-invasive audience cognitive patch to base prompt or skill doc."""
        if not self.profile.output_instructions:
            return base_prompt
        return f"{base_prompt.rstrip()}{self.profile.output_instructions}\n"


def parse_skill_modifiers(command_text: str) -> SkillModifierResult:
    """Extract known audience modifiers from command text or trailing flags.

    Example:
        >>> res = parse_skill_modifiers("/explain ELI5 quantum computing")
        >>> res.audience_depth
        <AudienceDepth.ELI5: 'eli5'>
        >>> res.clean_command
        '/explain quantum computing'
    """
    if not command_text:
        return SkillModifierResult(
            clean_command="",
            audience_depth=AudienceDepth.STANDARD,
            profile=_AUDIENCE_PROFILES[AudienceDepth.STANDARD],
            modifiers=(),
        )

    matched_modifiers: list[str] = []
    detected_depth = AudienceDepth.STANDARD

    words = command_text.split()
    kept_words: list[str] = []

    for word in words:
        clean_word = word.strip(":-_[]()").lower()
        if clean_word in _MODIFIER_ALIASES:
            matched_modifiers.append(word)
            detected_depth = _MODIFIER_ALIASES[clean_word]
        else:
            kept_words.append(word)

    clean_text = " ".join(kept_words)
    profile = _AUDIENCE_PROFILES[detected_depth]

    return SkillModifierResult(
        clean_command=clean_text,
        audience_depth=detected_depth,
        profile=profile,
        modifiers=tuple(matched_modifiers),
    )
