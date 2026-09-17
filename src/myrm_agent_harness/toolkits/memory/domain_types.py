"""Three-domain memory persona and experience partitions for OpenViking-style hierarchy.

[INPUT]
- None (Self-contained domain primitives and taxonomy definitions)

[OUTPUT]
- MemoryDomain: StrEnum of USER, ASSISTANT, TASK
- DomainCategory: StrEnum of 9 fine-grained sub-categories
- infer_domain_and_category: Heuristic classifier mapping memory attributes to domain and category

[POS]
Foundational memory domain ontology defining three overarching personas/partitions
and nine categories with automated categorization heuristics.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryDomain(StrEnum):
    """Three-domain memory partitions."""

    USER = "user"
    ASSISTANT = "assistant"
    TASK = "task"


class DomainCategory(StrEnum):
    """Nine fine-grained categories categorized under the three domains."""

    # User domain
    PROFILE = "profile"
    PREFERENCES = "preferences"
    ENTITIES = "entities"
    EVENTS = "events"

    # Assistant domain
    IDENTITY = "identity"
    SOUL = "soul"

    # Task domain
    EXPERIENCES = "experiences"
    TRAJECTORIES = "trajectories"
    TRAPS = "traps"


DOMAIN_CATEGORY_MAP: dict[MemoryDomain, list[DomainCategory]] = {
    MemoryDomain.USER: [
        DomainCategory.PROFILE,
        DomainCategory.PREFERENCES,
        DomainCategory.ENTITIES,
        DomainCategory.EVENTS,
    ],
    MemoryDomain.ASSISTANT: [
        DomainCategory.IDENTITY,
        DomainCategory.SOUL,
    ],
    MemoryDomain.TASK: [
        DomainCategory.EXPERIENCES,
        DomainCategory.TRAJECTORIES,
        DomainCategory.TRAPS,
    ],
}


CATEGORY_TO_DOMAIN_MAP: dict[DomainCategory, MemoryDomain] = {
    cat: domain
    for domain, categories in DOMAIN_CATEGORY_MAP.items()
    for cat in categories
}


def infer_domain_and_category(
    memory_type: str,
    content: str = "",
    event_type: str = "",
    preference_type: str | None = None,
    tags: list[str] | None = None,
) -> tuple[MemoryDomain, DomainCategory]:
    """Deterministically infer domain and fine-grained category from memory semantics.

    Args:
        memory_type: String representation of MemoryType (e.g. 'semantic', 'profile', 'episodic').
        content: Memory text body.
        event_type: Episodic event type if applicable.
        preference_type: Preference type ('explicit' | 'implicit') if applicable.
        tags: Optional tag list attached to the memory.

    Returns:
        A tuple of (MemoryDomain, DomainCategory).
    """
    clean_tags = [t.lower() for t in (tags or [])]
    lower_content = content.lower()

    # 1. Assistant domain cues (Identity & Soul)
    if any(k in clean_tags for k in ("soul", "persona", "assistant_soul", "agent_soul")):
        return MemoryDomain.ASSISTANT, DomainCategory.SOUL
    if any(k in clean_tags for k in ("identity", "role", "system_prompt", "agent_identity")):
        return MemoryDomain.ASSISTANT, DomainCategory.IDENTITY
    if any(lower_content.startswith(prefix) for prefix in ("i am ", "as an ai", "my role is", "my identity is")):
        return MemoryDomain.ASSISTANT, DomainCategory.IDENTITY

    # 2. Task domain cues (Traps, Trajectories, Experiences)
    if (
        event_type in ("pitfall", "trap", "failure")
        or any(k in clean_tags for k in ("trap", "pitfall", "failure", "negative_lesson"))
        or "mistake" in clean_tags
    ):
        return MemoryDomain.TASK, DomainCategory.TRAPS

    if (
        event_type in ("task_trajectory", "subtask", "sop")
        or any(k in clean_tags for k in ("trajectory", "sop", "workflow", "runbook", "guideline", "protocol"))
    ):
        return MemoryDomain.TASK, DomainCategory.TRAJECTORIES

    if (
        memory_type == "procedural"
        or any(k in clean_tags for k in ("experience", "rule", "procedure", "tool_rule"))
        or any(k in lower_content[:100] for k in ("guideline", "runbook", "sop", "protocol", "step-by-step"))
    ):
        return MemoryDomain.TASK, DomainCategory.EXPERIENCES

    # 3. User domain cues (Preferences, Profile, Entities, Events)
    if (
        preference_type is not None
        or any(k in clean_tags for k in ("preference", "habit", "favor"))
        or "likes" in clean_tags
        or "dislikes" in clean_tags
    ):
        return MemoryDomain.USER, DomainCategory.PREFERENCES

    if memory_type == "profile" or any(k in clean_tags for k in ("profile", "user_attribute", "bio", "demographics")):
        return MemoryDomain.USER, DomainCategory.PROFILE

    if any(k in clean_tags for k in ("entity", "contact", "organization", "project")):
        return MemoryDomain.USER, DomainCategory.ENTITIES

    if memory_type in ("episodic", "conversation") or event_type in ("conversation", "interaction"):
        return MemoryDomain.USER, DomainCategory.EVENTS

    # Default fallback: User Profile/Knowledge
    return MemoryDomain.USER, DomainCategory.PROFILE
