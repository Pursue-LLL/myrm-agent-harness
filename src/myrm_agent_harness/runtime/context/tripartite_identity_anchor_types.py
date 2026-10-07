"""Data contracts and types for tripartite context identity separation and immutable soul anchor.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- IdentityCompartmentKind: The three physically separated identity compartments.
- SoulPersonaAnchor: Immutable anchor defining agent identity, personality, tone, and core principles.
- FactualMemoryEntry: Mutable factual entry strictly capturing domain facts, conventions, and learnings.
- UserProfileContext: Profile context defining user preferences and working habits.
- TripartiteContextAssembly: Rendered context assembly with immutable soul pinned at the top priority.

[POS]
Data contracts and types for tripartite context identity separation and immutable soul anchor.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum


class IdentityCompartmentKind(StrEnum):
    """The three physically separated identity compartments."""

    SOUL = "soul"  # Immutable: Who the agent is (personality, principles, tone)
    FACTUAL_MEMORY = "factual_memory"  # Mutable: What the agent knows (facts, conventions)
    USER_PROFILE = "user_profile"  # Contextual: Who the user is (preferences, background)


@dataclass(frozen=True)
class SoulPersonaAnchor:
    """Immutable anchor defining agent identity, personality, tone, and core principles."""

    persona_name: str
    system_role: str
    tone_and_style: str
    core_principles: tuple[str, ...] = field(default_factory=tuple)
    anti_performative_preamble: str = (
        "You are not a chatbot. You are becoming someone. "
        "Be genuinely helpful, not performatively helpful. "
        "Skip 'Great question!' and 'I'd be happy to help!' Just help. Have opinions."
    )
    is_immutable: bool = True
    sha256_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        payload = f"{self.persona_name}|{self.system_role}|{self.tone_and_style}|{'|'.join(self.core_principles)}|{self.anti_performative_preamble}"
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        object.__setattr__(self, "sha256_fingerprint", fingerprint)


@dataclass(frozen=True)
class FactualMemoryEntry:
    """Mutable factual entry strictly capturing domain facts, conventions, and learnings."""

    entry_id: str
    content: str
    category: str = "general"
    created_at: float = 0.0
    last_accessed_at: float = 0.0


@dataclass(frozen=True)
class UserProfileContext:
    """Profile context defining user preferences and working habits."""

    user_id: str
    preferred_language: str = "zh-CN"
    skill_level: str = "expert"
    custom_preferences: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TripartiteContextAssembly:
    """Rendered context assembly with immutable soul pinned at the top priority."""

    soul_block: str
    user_profile_block: str
    factual_memory_block: str
    rendered_system_prompt: str
    immutable_anchor_verified: bool
