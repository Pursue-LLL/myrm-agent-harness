"""Canonical agent workspace protocol and lifecycle package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- ActorVoiceMode: Dual-track voice switch (In-character persona vs Real-talk transparent engineering).
- AdaptivePersonaPolicy: Resolved active policy configuration.
- AdaptivePersonaPolicyEngine: Evaluates relationship maturity stage, input vibes, and critical incident overrides.
- AgentIdentitySpec: Structured identity details (Name, Creature, Vibe, Emoji, Avatar).
- BootstrapLifecycleRunner: Executes birth sequences and securely prunes BOOTSTRAP.md after completion.
- BootstrapRitualState: Status of the onboarding birth sequence.
- CanonicalAgentWorkspaceProtocolAndLifecycleSuite: Unified facade coordinating canonical 5-file protocols.
- CanonicalFileKind: Standard 5 workspace files (SOUL, IDENTITY, USER, BOOTSTRAP, TOOLS).
- CanonicalFileParser: Robust parser extracting structured identity, directives, and birth sequences.
- CanonicalWorkspaceBundle: Bound aggregation of parsed workspace files and dynamic policy.
- CanonicalWorkspaceProtocolSuite: Convenient alias.
- DirectiveStatus: Lifecycle state machine for user directives (ACTIVE, SUPERSEDED).
- MergedWorkspaceContext: Consolidated context containing coexisting persona and engineering rule layers.
- MultiTierWorkspaceMerger: Merges SOUL, AGENTS, CLAUDE, and USER files without silent discarding.
- RelationshipMaturityStage: Relationship progression (Day 1 onboarding, Day 7, Day 40 veteran).
- RuntimeVibe: Contextual tone adaptation (Concise command, Exploratory, Urgent incident).
- UserDirectiveItem: Single timestamped preference with 4000-char budget containment.

[POS]
Package entry point for Item 313 CanonicalAgentWorkspaceProtocolAndLifecycleSuite.
"""

from .adaptive_persona_policy_engine import (
    AdaptivePersonaPolicy,
    AdaptivePersonaPolicyEngine,
)
from .bootstrap_lifecycle_runner import (
    BootstrapLifecycleRunner,
    BootstrapRitualState,
)
from .canonical_file_parser import CanonicalFileParser
from .canonical_types import (
    ActorVoiceMode,
    AgentIdentitySpec,
    CanonicalFileKind,
    CanonicalWorkspaceBundle,
    DirectiveStatus,
    RelationshipMaturityStage,
    RuntimeVibe,
    UserDirectiveItem,
)
from .canonical_workspace_protocol_suite import (
    CanonicalAgentWorkspaceProtocolAndLifecycleSuite,
    CanonicalWorkspaceProtocolSuite,
)
from .multi_tier_workspace_merger import (
    MergedWorkspaceContext,
    MultiTierWorkspaceMerger,
)

__all__ = [
    "ActorVoiceMode",
    "AdaptivePersonaPolicy",
    "AdaptivePersonaPolicyEngine",
    "AgentIdentitySpec",
    "BootstrapLifecycleRunner",
    "BootstrapRitualState",
    "CanonicalAgentWorkspaceProtocolAndLifecycleSuite",
    "CanonicalFileKind",
    "CanonicalFileParser",
    "CanonicalWorkspaceBundle",
    "CanonicalWorkspaceProtocolSuite",
    "DirectiveStatus",
    "MergedWorkspaceContext",
    "MultiTierWorkspaceMerger",
    "RelationshipMaturityStage",
    "RuntimeVibe",
    "UserDirectiveItem",
]
