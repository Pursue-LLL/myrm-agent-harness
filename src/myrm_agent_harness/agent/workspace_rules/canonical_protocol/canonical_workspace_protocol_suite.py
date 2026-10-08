# [INPUT]: AdaptivePersonaPolicy, AdaptivePersonaPolicyEngine, BootstrapLifecycleRunner, BootstrapRitualState, CanonicalFileParser, CanonicalWorkspaceBundle, MergedWorkspaceContext, MultiTierWorkspaceMerger, Path
# [OUTPUT]: CanonicalAgentWorkspaceProtocolAndLifecycleSuite, CanonicalWorkspaceProtocolSuite
# [POS]: agent/workspace_rules/canonical_protocol/canonical_workspace_protocol_suite.py

"""Comprehensive facade suite for canonical workspace protocols, multi-tier merging, and dynamic policy evolution.

[INPUT]
- CanonicalWorkspaceBundle, MergedWorkspaceContext, AdaptivePersonaPolicy, BootstrapRitualState: Contract models.
- CanonicalFileParser, MultiTierWorkspaceMerger, AdaptivePersonaPolicyEngine, BootstrapLifecycleRunner: Underlying engines.

[OUTPUT]
- CanonicalAgentWorkspaceProtocolAndLifecycleSuite: Primary facade for Item 313.
- CanonicalWorkspaceProtocolSuite: Convenient alias.

[POS]
Main entry point coordinating canonical OpenClaw/Muse files, non-exclusive merging, and dynamic behavioral policy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from .adaptive_persona_policy_engine import (
    AdaptivePersonaPolicy,
    AdaptivePersonaPolicyEngine,
)
from .bootstrap_lifecycle_runner import (
    BootstrapLifecycleRunner,
    BootstrapRitualState,
)
from .canonical_file_parser import CanonicalFileParser
from .canonical_types import CanonicalWorkspaceBundle
from .multi_tier_workspace_merger import (
    MergedWorkspaceContext,
    MultiTierWorkspaceMerger,
)


class CanonicalAgentWorkspaceProtocolAndLifecycleSuite:
    """Unified facade managing canonical 5-file contracts, multi-tier rule merging, and dynamic policy."""

    def __init__(self) -> None:
        self._parser = CanonicalFileParser()
        self._merger = MultiTierWorkspaceMerger(self._parser)
        self._policy_engine = AdaptivePersonaPolicyEngine()
        self._bootstrap_runner = BootstrapLifecycleRunner()

    def load_canonical_workspace(self, directory: Path) -> CanonicalWorkspaceBundle:
        """Parse all 5 canonical workspace files in the given directory."""
        return self._parser.parse_workspace_directory(directory)

    def merge_workspace_context(self, directory: Path) -> MergedWorkspaceContext:
        """Merge persona rules and engineering instructions into structured coexisting layers."""
        return self._merger.merge_workspace(directory)

    def evaluate_adaptive_policy(
        self,
        collaboration_days: int = 1,
        user_query: str = "",
        system_incident: bool = False,
    ) -> AdaptivePersonaPolicy:
        """Derive the effective dynamic behavioral policy (maturity stage, vibe, real-talk voice)."""
        return self._policy_engine.synthesize_policy(
            collaboration_days=collaboration_days,
            user_query=user_query,
            system_incident=system_incident,
        )

    def check_bootstrap_status(self, directory: Path) -> BootstrapRitualState:
        """Inspect if the workspace has an active BOOTSTRAP.md birth sequence."""
        return self._bootstrap_runner.check_bootstrap_status(directory)

    def complete_and_prune_bootstrap(self, directory: Path) -> bool:
        """Safely prune BOOTSTRAP.md once initialization ritual is accomplished."""
        return self._bootstrap_runner.complete_and_prune_bootstrap(directory)

    def compile_full_workspace_injection(
        self,
        directory: Path,
        collaboration_days: int = 1,
        user_query: str = "",
        system_incident: bool = False,
    ) -> str:
        """Assemble all layers and dynamic policy into a unified system prompt context block."""
        merged = self.merge_workspace_context(directory)
        policy = self.evaluate_adaptive_policy(
            collaboration_days=collaboration_days,
            user_query=user_query,
            system_incident=system_incident,
        )
        bootstrap = self.check_bootstrap_status(directory)

        sections: list[str] = [
            policy.policy_instruction,
            merged.render_full_system_prompt_block(),
        ]

        if bootstrap.has_pending_bootstrap:
            sections.append(bootstrap.ritual_instruction)

        return "\n\n".join(s for s in sections if s.strip()).strip()

    def export_dossier_deck_metadata(self, directory: Path) -> Mapping[str, object]:
        """Export structured metadata powering frontend Normie-Friendly Digital Employee Dossier UI."""
        bundle = self.load_canonical_workspace(directory)
        ident = bundle.identity
        return {
            "identity": {
                "name": ident.name,
                "creature": ident.creature,
                "vibe": ident.vibe,
                "emoji": ident.emoji,
                "avatar_url": ident.avatar_url,
            },
            "soul_configured": bool(bundle.soul_content),
            "soul_snippet": bundle.soul_content[:180] if bundle.soul_content else "",
            "active_directives_count": len(bundle.active_user_directives),
            "superseded_directives_count": len(bundle.superseded_user_directives),
            "tools_configured": bool(bundle.tools_guidance),
            "bootstrap_pending": bundle.bootstrap_pending,
            "loaded_files": list(bundle.loaded_files),
        }


CanonicalWorkspaceProtocolSuite = CanonicalAgentWorkspaceProtocolAndLifecycleSuite
