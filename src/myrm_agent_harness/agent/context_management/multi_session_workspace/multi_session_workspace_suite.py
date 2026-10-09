"""Master facade suite for multi-session parallel workspace and root discovery.

[INPUT]
- workspace_types: All contracts, layouts, slots, bundles, and configuration models.
- project_root_sniffer: ProjectRootSniffer.
- parallel_workspace_deck: ParallelWorkspaceDeck.
- cross_session_reference_bus: CrossSessionReferenceBus.

[OUTPUT]
- MultiSessionParallelWorkspaceAndRootDiscoverySuite: Master facade unifying
  smart project root sniffing, multi-column parallel session decks, and cross-session reference.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.multi_session_workspace
- Module: multi_session_workspace_suite.py
"""

from pathlib import Path
from typing import Optional, Sequence, Union

from myrm_agent_harness.agent.context_management.multi_session_workspace.cross_session_reference_bus import (
    CrossSessionReferenceBus,
)
from myrm_agent_harness.agent.context_management.multi_session_workspace.parallel_workspace_deck import (
    ParallelWorkspaceDeck,
)
from myrm_agent_harness.agent.context_management.multi_session_workspace.project_root_sniffer import (
    ProjectRootSniffer,
)
from myrm_agent_harness.agent.context_management.multi_session_workspace.workspace_types import (
    CrossSessionArtifactItem,
    CrossSessionReferenceBundle,
    DiscoveredRootResult,
    GridLayoutType,
    MultiSessionWorkspaceConfig,
    SlotRoleTag,
    WorkspaceDeckState,
)


class MultiSessionParallelWorkspaceAndRootDiscoverySuite:
    """Master facade coordinating project root discovery, parallel split decks, and cross-session buses."""

    def __init__(self, config: Optional[MultiSessionWorkspaceConfig] = None) -> None:
        self._config = config or MultiSessionWorkspaceConfig()
        self._root_sniffer = ProjectRootSniffer(self._config)
        self._workspace_deck = ParallelWorkspaceDeck(self._config)
        self._reference_bus = CrossSessionReferenceBus(self._config)

    @property
    def root_sniffer(self) -> ProjectRootSniffer:
        """Access the project root discovery sniffer."""
        return self._root_sniffer

    @property
    def workspace_deck(self) -> ParallelWorkspaceDeck:
        """Access the multi-session parallel workspace deck."""
        return self._workspace_deck

    @property
    def reference_bus(self) -> CrossSessionReferenceBus:
        """Access the cross-session state reference bus."""
        return self._reference_bus

    def discover_project_root(
        self,
        starting_path: Union[str, Path],
        sandbox_boundary: Optional[Union[str, Path]] = None,
    ) -> DiscoveredRootResult:
        """Heuristically identifies authentic project root to eliminate manual navigation friction.

        Args:
            starting_path: Initial directory or file location.
            sandbox_boundary: Optional outer boundary preventing path traversal escaping.

        Returns:
            DiscoveredRootResult with root location, confidence score, and found markers.
        """
        path_obj = Path(starting_path)
        boundary_obj = Path(sandbox_boundary) if sandbox_boundary is not None else None
        return self._root_sniffer.discover_root(
            starting_path=path_obj,
            sandbox_boundary=boundary_obj,
        )

    def configure_workspace_layout(
        self,
        new_layout: GridLayoutType,
        initial_sessions: Optional[Sequence[str]] = None,
    ) -> WorkspaceDeckState:
        """Configures the viewport grid layout (Single, 1x2, 2x2, Tabbed)."""
        return self._workspace_deck.reconfigure_layout(
            new_layout=new_layout,
            initial_sessions=initial_sessions,
        )

    def dock_session_to_slot(
        self,
        slot_id: str,
        session_id: str,
        slot_title: Optional[str] = None,
        role_tag: Optional[SlotRoleTag] = None,
    ) -> WorkspaceDeckState:
        """Docks a session into an active workspace viewport slot."""
        return self._workspace_deck.dock_session(
            slot_id=slot_id,
            session_id=session_id,
            slot_title=slot_title,
            role_tag=role_tag,
        )

    def focus_viewport_slot(self, slot_id: str) -> WorkspaceDeckState:
        """Switches user or execution focus to the specified slot."""
        return self._workspace_deck.focus_slot(slot_id)

    def register_peer_session_state(
        self,
        session_id: str,
        session_title: str,
        key_findings_summary: str,
        artifacts: Optional[Sequence[CrossSessionArtifactItem]] = None,
    ) -> None:
        """Registers a session's deliverables and conclusions for cross-session access."""
        self._reference_bus.register_session_state(
            session_id=session_id,
            session_title=session_title,
            key_findings_summary=key_findings_summary,
            artifacts=artifacts,
        )

    def extract_cross_session_context(
        self,
        source_session_id: str,
        target_session_id: str,
    ) -> CrossSessionReferenceBundle:
        """Extracts peer session context into a reference bundle."""
        return self._reference_bus.extract_reference_bundle(
            source_session_id=source_session_id,
            target_session_id=target_session_id,
        )

    def render_cross_session_prompt_context(
        self,
        bundle: CrossSessionReferenceBundle,
    ) -> str:
        """Renders an prompt block embedding the referenced session's conclusions."""
        return self._reference_bus.render_cross_session_prompt(bundle)
