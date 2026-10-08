# [INPUT]: None
# [OUTPUT]: ActorVoiceMode, AgentIdentitySpec, CanonicalFileKind, CanonicalWorkspaceBundle, DirectiveStatus, RelationshipMaturityStage, RuntimeVibe, UserDirectiveItem
# [POS]: agent/workspace_rules/canonical_protocol/canonical_types.py

"""Domain models and contracts for canonical agent workspace protocol and lifecycle suite.

[INPUT]
- None (Self-contained domain definitions).

[OUTPUT]
- CanonicalFileKind: Standard 5 workspace files (SOUL, IDENTITY, USER, BOOTSTRAP, TOOLS).
- AgentIdentitySpec: Structured identity details (Name, Creature, Vibe, Emoji, Avatar).
- DirectiveStatus: Lifecycle state machine for user directives (ACTIVE, SUPERSEDED).
- UserDirectiveItem: Single timestamped preference with 4000-char budget containment.
- RelationshipMaturityStage: Relationship progression (Day 1 onboarding, Day 7, Day 40 veteran).
- RuntimeVibe: Contextual tone adaptation (Concise command, Exploratory, Urgent incident).
- ActorVoiceMode: Dual-track voice switch (In-character persona vs Real-talk transparent engineering).
- CanonicalWorkspaceBundle: Bound aggregation of parsed workspace files and dynamic policy.

[POS]
Domain contract layer for Item 313 CanonicalAgentWorkspaceProtocolAndLifecycleSuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class CanonicalFileKind(str, Enum):
    """The 5 canonical workspace configuration files established by OpenClaw & Meta Muse."""

    SOUL = "SOUL.md"          # Persona tone, brevity, and behavioral boundaries
    IDENTITY = "IDENTITY.md"  # Structured identity: Name, Creature, Vibe, Emoji, Avatar
    USER = "USER.md"          # User preferences with timestamped directives and 4000-char budget
    BOOTSTRAP = "BOOTSTRAP.md"# First-run birth sequence ritual (pruned after execution)
    TOOLS = "TOOLS.md"        # Local toolchain hints, execution rules, and parameter guidance


class DirectiveStatus(str, Enum):
    """Lifecycle state machine for USER.md directives."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"


class RelationshipMaturityStage(str, Enum):
    """Relationship progression based on cumulative days of collaboration."""

    DAY_1_ONBOARDING = "day_1"       # Humble, explicit confirmations, verbose step-by-step
    DAY_7_COLLABORATIVE = "day_7"     # Balanced speed, proactive suggestions, standard detail
    DAY_40_VETERAN_SYNERGY = "day_40"# Zero-fluff, understands abbreviations, military brevity


class RuntimeVibe(str, Enum):
    """Dynamic conversational tone adapted to immediate user context."""

    CONCISE_COMMAND = "concise_command"         # Fast execution, minimal text
    EXPLORATORY_THINKING = "exploratory"        # Brainstorming, architectural trade-offs
    URGENT_INCIDENT = "urgent_incident"         # Critical error, production triage, real-talk


class ActorVoiceMode(str, Enum):
    """Dual-track voice arbitration mode."""

    IN_CHARACTER = "in_character"  # Engaging, stylized persona active
    REAL_TALK = "real_talk"        # Transparent, objective engineer voice for safety & failures


@dataclass(frozen=True)
class AgentIdentitySpec:
    """Structured identity parameters extracted from IDENTITY.md."""

    name: str = "Myrm"
    creature: str = "Assistant"
    vibe: str = "Helpful and Direct"
    emoji: str = "🤖"
    avatar_url: str = ""
    extra_attributes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class UserDirectiveItem:
    """Individual user preference extracted from USER.md."""

    statement: str
    observed_date: str = ""
    status: DirectiveStatus = DirectiveStatus.ACTIVE


@dataclass(frozen=True)
class CanonicalWorkspaceBundle:
    """Aggregated parsed state of all canonical workspace files."""

    identity: AgentIdentitySpec
    soul_content: str
    active_user_directives: Sequence[UserDirectiveItem]
    superseded_user_directives: Sequence[UserDirectiveItem]
    tools_guidance: str
    bootstrap_pending: bool
    bootstrap_content: str
    loaded_files: Sequence[str] = field(default_factory=tuple)
