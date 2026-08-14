"""Domain Extraction Presets — strategy guidance for memory extraction.

Provides domain-specific property hints that are injected into the extraction
LLM prompt, improving recall precision for entity attributes relevant to the
configured Agent persona.

[INPUT]
- ExtractionConfig.domain_preset: str (from Agent Profile)

[OUTPUT]
- build_domain_hints_section: Formatted prompt section for extraction guidance
- auto_detect_preset: Keyword-based preset inference from Agent system prompt

[POS]
Domain extraction preset data and prompt section builder for the memory extractor.
"""

from __future__ import annotations

from enum import StrEnum


class DomainPreset(StrEnum):
    """Available domain extraction presets."""

    NONE = "none"
    PERSONA = "persona"
    WORK_ASSISTANT = "work_assistant"
    RESEARCH = "research"


_PERSONA_HINTS: tuple[tuple[str, str], ...] = (
    ("location", "Track location changes with old/new values and approximate timestamp"),
    ("occupation", "Career events: title, company, start date, reason for change"),
    ("relationships", "Key people: name, relationship type, context of mention"),
    ("health", "Health events or conditions mentioned (never fabricate)"),
    ("hobbies", "Interests, activities, sports with frequency/skill level"),
    ("daily_routine", "Wake/sleep times, commute, recurring habits"),
    ("life_events", "Milestones: moves, graduations, births, anniversaries"),
    ("preferences", "Food, music, travel, entertainment with specifics"),
    ("pets", "Pet names, species, age, health notes"),
    ("goals", "Personal aspirations with timeline if mentioned"),
)

_WORK_ASSISTANT_HINTS: tuple[tuple[str, str], ...] = (
    ("tech_stack", "Languages, frameworks, tools with versions when stated"),
    ("project_decisions", "Architecture/design decisions with rationale and context"),
    ("team_context", "Team members, roles, reporting lines"),
    ("deadlines", "Project milestones with dates and deliverables"),
    ("blockers", "Current obstacles, dependencies, waiting items"),
    ("meeting_outcomes", "Decisions made, action items assigned"),
    ("code_conventions", "Style rules, naming patterns, forbidden patterns"),
    ("infrastructure", "Deployment targets, CI/CD, cloud services"),
    ("business_rules", "Domain constraints that affect implementation"),
    ("priorities", "Current sprint focus, P0/P1 items"),
)

_RESEARCH_HINTS: tuple[tuple[str, str], ...] = (
    ("research_topics", "Active research questions and hypotheses"),
    ("sources", "Papers, books, URLs with relevance notes"),
    ("methodology", "Preferred research methods and frameworks"),
    ("findings", "Key conclusions with confidence level"),
    ("contradictions", "Conflicting evidence or evolving positions"),
    ("terminology", "Domain-specific terms with user's definitions"),
    ("collaborators", "Co-researchers, advisors, institutions"),
    ("datasets", "Data sources, sizes, access methods"),
    ("timeline", "Research phases, submission deadlines"),
    ("open_questions", "Unresolved issues flagged for follow-up"),
)

_PRESET_HINTS: dict[DomainPreset, tuple[tuple[str, str], ...]] = {
    DomainPreset.PERSONA: _PERSONA_HINTS,
    DomainPreset.WORK_ASSISTANT: _WORK_ASSISTANT_HINTS,
    DomainPreset.RESEARCH: _RESEARCH_HINTS,
}

_AUTO_DETECT_KEYWORDS: dict[DomainPreset, tuple[str, ...]] = {
    DomainPreset.PERSONA: (
        "companion",
        "friend",
        "伴侣",
        "生活助手",
        "personal",
        "日常",
        "life",
    ),
    DomainPreset.WORK_ASSISTANT: (
        "work",
        "assistant",
        "工作",
        "办公",
        "professional",
        "productivity",
    ),
    DomainPreset.RESEARCH: (
        "research",
        "academic",
        "研究",
        "学术",
        "analysis",
        "scientist",
    ),
}


def build_domain_hints_section(preset: DomainPreset | str) -> str:
    """Build a prompt section with domain-specific extraction hints.

    Returns empty string for NONE preset or unknown values (zero-cost path).
    """
    if isinstance(preset, str):
        try:
            preset = DomainPreset(preset)
        except ValueError:
            return ""

    hints = _PRESET_HINTS.get(preset)
    if not hints:
        return ""

    lines = [
        "\n## Domain Priority Attributes",
        "",
        "When the conversation touches these topics, extract with HIGH PRIORITY",
        "(only when genuinely present — do NOT fabricate):",
    ]
    for key, guidance in hints:
        lines.append(f"- **{key}**: {guidance}")

    return "\n".join(lines)


def auto_detect_preset(system_prompt: str) -> DomainPreset:
    """Infer domain preset from Agent system prompt via keyword matching.

    Returns NONE if no keywords match. User-explicit selection always overrides.
    """
    if not system_prompt:
        return DomainPreset.NONE

    lower = system_prompt.lower()
    for preset, keywords in _AUTO_DETECT_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return preset
    return DomainPreset.NONE
