"""Comprehensive tests for MultiSessionParallelWorkspaceAndRootDiscoverySuite.

[INPUT]
- multi_session_workspace package contracts and implementations.

[OUTPUT]
- Deterministic verification of heuristic project root discovery, sandbox boundary safety,
  parallel workspace deck layouts, and cross-session reference bus prompt rendering.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_multi_session_workspace_suite.py
"""

from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_management.multi_session_workspace import (
    CrossSessionArtifactItem,
    CrossSessionReferenceBundle,
    CrossSessionReferenceBus,
    DiscoveredRootResult,
    GridLayoutType,
    MultiSessionParallelWorkspaceAndRootDiscoverySuite,
    MultiSessionWorkspaceConfig,
    ParallelWorkspaceDeck,
    ProjectRootSniffer,
    RootIndicatorKind,
    SlotRoleTag,
    WorkspaceDeckState,
    WorkspaceSlot,
)


def test_project_root_sniffer_heuristics_and_monorepo(tmp_path: Path) -> None:
    """Verifies upward root discovery, monorepo marker identification, and fallback behavior."""
    sniffer = ProjectRootSniffer()

    # Scenario 1: Standard git + python project
    repo_root = tmp_path / "my_python_repo"
    sub_pkg = repo_root / "src" / "pkg" / "nested"
    sub_pkg.mkdir(parents=True)
    (repo_root / ".git").mkdir()
    (repo_root / "pyproject.toml").write_text("[project]\nname='test'", encoding="utf-8")

    res_python = sniffer.discover_root(starting_path=sub_pkg)
    assert res_python.discovered_root == repo_root.resolve()
    assert res_python.confidence_score >= 80.0
    assert ".git" in res_python.indicators_found
    assert "pyproject.toml" in res_python.indicators_found
    assert res_python.traversal_depth == 3
    assert res_python.is_monorepo_root is False

    # Scenario 2: Monorepo workspace detection
    monorepo_root = tmp_path / "my_monorepo"
    package_dir = monorepo_root / "packages" / "frontend"
    package_dir.mkdir(parents=True)
    (monorepo_root / "pnpm-workspace.yaml").write_text("packages: ['packages/*']", encoding="utf-8")
    (monorepo_root / "package.json").write_text('{"name": "root"}', encoding="utf-8")

    res_mono = sniffer.discover_root(starting_path=package_dir)
    assert res_mono.discovered_root == monorepo_root.resolve()
    assert res_mono.is_monorepo_root is True
    assert "pnpm-workspace.yaml" in res_mono.indicators_found

    # Scenario 3: Isolated directory without markers fallbacks to starting path
    empty_dir = tmp_path / "empty_folder"
    empty_dir.mkdir()
    res_empty = sniffer.discover_root(starting_path=empty_dir)
    assert res_empty.discovered_root == empty_dir.resolve()
    assert res_empty.confidence_score == 0.0
    assert len(res_empty.indicators_found) == 0


def test_project_root_sniffer_sandbox_boundary_protection(tmp_path: Path) -> None:
    """Verifies that directory upward traversal strictly honors sandbox boundary to prevent escaping."""
    sniffer = ProjectRootSniffer()

    # Outside parent repo with git
    host_dir = tmp_path / "host_system"
    host_dir.mkdir()
    (host_dir / ".git").mkdir()

    # Sandbox guest mount
    sandbox_mount = host_dir / "guest_sandbox"
    guest_sub = sandbox_mount / "app" / "work"
    guest_sub.mkdir(parents=True)

    # Traversal with boundary prevents ascending into host_system/.git
    res_bounded = sniffer.discover_root(
        starting_path=guest_sub,
        sandbox_boundary=sandbox_mount,
    )
    # Must not escape past sandbox_mount
    assert res_bounded.discovered_root == guest_sub.resolve()
    assert ".git" not in res_bounded.indicators_found


def test_parallel_workspace_deck_layouts_and_focus() -> None:
    """Verifies slot allocation across split layouts, session docking, and focus management."""
    deck = ParallelWorkspaceDeck()

    # 1. Initial single layout
    initial_snap = deck.get_state_snapshot()
    assert initial_snap.layout_type == GridLayoutType.SINGLE
    assert len(initial_snap.slots) == 1
    assert initial_snap.active_slot_id == "slot-0"

    # 2. Split horizontal (1x2 columns)
    split_snap = deck.reconfigure_layout(
        new_layout=GridLayoutType.SPLIT_HORIZONTAL,
        initial_sessions=["session-main-001"],
    )
    assert split_snap.layout_type == GridLayoutType.SPLIT_HORIZONTAL
    assert len(split_snap.slots) == 2
    assert split_snap.slots[0].assigned_session_id == "session-main-001"
    assert split_snap.slots[1].assigned_session_id is None

    # 3. Dock second session as copilot
    docked_snap = deck.dock_session(
        slot_id="slot-1",
        session_id="session-copilot-002",
        slot_title="Interactive Scheme",
        role_tag=SlotRoleTag.INTERACTIVE_COPILOT,
    )
    assert docked_snap.total_active_sessions == 2
    assert docked_snap.slots[1].assigned_session_id == "session-copilot-002"
    assert docked_snap.slots[1].role_tag == SlotRoleTag.INTERACTIVE_COPILOT

    # 4. Focus switching
    focus_snap = deck.focus_slot("slot-1")
    assert focus_snap.active_slot_id == "slot-1"
    assert focus_snap.slots[1].is_focused is True
    assert focus_snap.slots[0].is_focused is False

    # 5. Undocking session
    released_snap = deck.release_session("session-main-001")
    assert released_snap.slots[0].assigned_session_id is None
    assert released_snap.total_active_sessions == 1


def test_cross_session_reference_bus_bridge_and_prompt() -> None:
    """Verifies state registration, artifact association, and prompt synthesis."""
    bus = CrossSessionReferenceBus()

    artifacts = [
        CrossSessionArtifactItem(
            artifact_id="art-1",
            name="migration_plan.sql",
            mime_type="application/sql",
            summary_preview="Schema diff with 4 index additions",
            uri="/workspace/db/migration_plan.sql",
        )
    ]

    # 1. Register session findings
    bus.register_session_state(
        session_id="session-origin-88",
        session_title="Database Refactor Task",
        key_findings_summary="Successfully optimized query performance by 85%.",
        artifacts=artifacts,
    )

    # 2. Extract reference bundle
    bundle = bus.extract_reference_bundle(
        source_session_id="session-origin-88",
        target_session_id="session-target-99",
    )
    assert bundle.source_session_id == "session-origin-88"
    assert bundle.target_session_id == "session-target-99"
    assert bundle.session_title == "Database Refactor Task"
    assert len(bundle.salvaged_artifacts) == 1
    assert len(bundle.reference_digest) == 16

    # 3. Render prompt block
    prompt = bus.render_cross_session_prompt(bundle)
    assert "[CROSS_SESSION_CONTEXT" in prompt
    assert "Database Refactor Task" in prompt
    assert "optimized query performance by 85%" in prompt
    assert "migration_plan.sql" in prompt
    assert "Schema diff with 4 index additions" in prompt
    assert "[/CROSS_SESSION_CONTEXT]" in prompt


def test_multi_session_workspace_suite_facade_end_to_end(tmp_path: Path) -> None:
    """Verifies the unified facade coordinating root discovery, parallel deck, and cross-session bus."""
    suite = MultiSessionParallelWorkspaceAndRootDiscoverySuite()

    # 1. Heuristic project root discovery
    project_dir = tmp_path / "acme_project"
    sub_dir = project_dir / "modules" / "api"
    sub_dir.mkdir(parents=True)
    (project_dir / "Cargo.toml").write_text('[workspace]\nmembers=["modules/*"]', encoding="utf-8")

    root_res = suite.discover_project_root(starting_path=sub_dir)
    assert root_res.discovered_root == project_dir.resolve()
    assert "Cargo.toml" in root_res.indicators_found

    # 2. Configure multi-session quad grid
    deck_state = suite.configure_workspace_layout(GridLayoutType.QUAD_GRID)
    assert len(deck_state.slots) == 4

    # 3. Dock primary worker & background auditor
    suite.dock_session_to_slot("slot-0", "sess-build", "Rust Builder", SlotRoleTag.PRIMARY_WORKER)
    suite.dock_session_to_slot("slot-1", "sess-test", "Cargo Test", SlotRoleTag.BACKGROUND_AUDITOR)
    suite.focus_viewport_slot("slot-1")

    # 4. Cross-session conclusion sharing
    suite.register_peer_session_state(
        session_id="sess-build",
        session_title="Rust Compilation Run",
        key_findings_summary="Release binary compiled in 1.4s with 0 warnings.",
    )
    bundle = suite.extract_cross_session_context("sess-build", "sess-test")
    prompt = suite.render_cross_session_prompt_context(bundle)

    assert "Rust Compilation Run" in prompt
    assert "Release binary compiled in 1.4s" in prompt
