"""Unit tests for Per-Project Workspace Team Blueprint Auto-Reuse (Item 36).

[INPUT]
- myrm_agent_harness.agent.coordination.workspace_blueprint::{
    AutoReusePolicy,
    WorkspaceBlueprintBinding,
    WorkspaceBlueprintStore,
  }

[OUTPUT]
- Pytest test cases verifying workspace binding, resolution branches, LRU recent recommendations,
  usage recording, unbind, and thread safety.

[POS]
- myrm-agent-harness/tests/agent/coordination/test_workspace_blueprint.py
"""

from __future__ import annotations

import concurrent.futures

import pytest

from myrm_agent_harness.agent.coordination.workspace_blueprint import (
    AutoReusePolicy,
    WorkspaceBlueprintStore,
)


@pytest.fixture
def store() -> WorkspaceBlueprintStore:
    return WorkspaceBlueprintStore()


def test_bind_and_list_bindings(store: WorkspaceBlueprintStore) -> None:
    binding1 = store.bind_blueprint(
        workspace_id="ws_frontend_app",
        blueprint_id="bp_frontend_trio",
        team_name="Frontend Craft Squad",
        auto_reuse_policy=AutoReusePolicy.ALWAYS_REUSE,
        member_count=3,
        total_budget_tokens=120000,
        project_label="NextJS Webapp",
        blueprint_snapshot={"lead": "orchestrator", "coder": "ui_specialist"},
    )
    assert binding1.workspace_id == "ws_frontend_app"
    assert binding1.blueprint_id == "bp_frontend_trio"
    assert binding1.auto_reuse_policy == AutoReusePolicy.ALWAYS_REUSE
    assert binding1.member_count == 3

    # Direct lookup
    looked_up = store.get_binding("ws_frontend_app")
    assert looked_up is not None
    assert looked_up.team_name == "Frontend Craft Squad"

    # List bindings
    all_bindings = store.list_bindings()
    assert len(all_bindings) == 1
    assert all_bindings[0].workspace_id == "ws_frontend_app"


def test_resolve_policy_branches(store: WorkspaceBlueprintStore) -> None:
    # 1. ALWAYS_REUSE
    store.bind_blueprint(
        workspace_id="ws_auto",
        blueprint_id="bp_auto",
        team_name="Auto Squad",
        auto_reuse_policy=AutoReusePolicy.ALWAYS_REUSE,
    )
    res_auto = store.resolve_blueprint("ws_auto")
    assert res_auto.can_auto_instantiate is True
    assert res_auto.status_label == "auto_instantiable"
    assert res_auto.binding is not None
    assert res_auto.binding.team_name == "Auto Squad"

    # 2. PROMPT_REUSE
    store.bind_blueprint(
        workspace_id="ws_prompt",
        blueprint_id="bp_prompt",
        team_name="Prompt Squad",
        auto_reuse_policy=AutoReusePolicy.PROMPT_REUSE,
    )
    res_prompt = store.resolve_blueprint("ws_prompt")
    assert res_prompt.can_auto_instantiate is False
    assert res_prompt.status_label == "prompt_candidate"
    assert "confirm reuse" in res_prompt.resolution_rationale

    # 3. MANUAL_ONLY
    store.bind_blueprint(
        workspace_id="ws_manual",
        blueprint_id="bp_manual",
        team_name="Manual Squad",
        auto_reuse_policy=AutoReusePolicy.MANUAL_ONLY,
    )
    res_manual = store.resolve_blueprint("ws_manual")
    assert res_manual.can_auto_instantiate is False
    assert res_manual.status_label == "manual_only"


def test_unbound_workspace_fallback_and_recommendation(store: WorkspaceBlueprintStore) -> None:
    # When store is empty, unbound resolution returns no template
    res_empty = store.resolve_blueprint("ws_unknown")
    assert res_empty.binding is None
    assert res_empty.can_auto_instantiate is False
    assert res_empty.status_label == "unbound_no_template"

    # Bind one workspace
    store.bind_blueprint(
        workspace_id="ws_active_backend",
        blueprint_id="bp_backend_dev",
        team_name="Backend Core Team",
        auto_reuse_policy=AutoReusePolicy.PROMPT_REUSE,
    )

    # Resolving another unbound workspace should recommend the most recent active team
    res_recommend = store.resolve_blueprint("ws_brand_new_project")
    assert res_recommend.can_auto_instantiate is False
    assert res_recommend.status_label == "unbound_recommend_recent"
    assert res_recommend.binding is not None
    assert res_recommend.binding.team_name == "Backend Core Team"
    assert "Recommending" in res_recommend.resolution_rationale


def test_record_usage_and_unbind(store: WorkspaceBlueprintStore) -> None:
    store.bind_blueprint(
        workspace_id="ws_01",
        blueprint_id="bp_01",
        team_name="Team One",
    )
    store.bind_blueprint(
        workspace_id="ws_02",
        blueprint_id="bp_02",
        team_name="Team Two",
    )

    # Most recent should be ws_02
    recent = store.get_most_recent_binding()
    assert recent is not None
    assert recent.workspace_id == "ws_02"

    # Now record usage for ws_01
    assert store.record_usage("ws_01") is True
    # Now most recent should be ws_01
    recent_after = store.get_most_recent_binding()
    assert recent_after is not None
    assert recent_after.workspace_id == "ws_01"

    # Record usage for non-existent workspace returns False
    assert store.record_usage("ws_non_existent") is False

    # Unbind ws_01
    assert store.unbind_blueprint("ws_01") is True
    assert store.get_binding("ws_01") is None
    assert store.unbind_blueprint("ws_01") is False

    # Clear store
    store.clear()
    assert len(store.list_bindings()) == 0
    assert store.get_most_recent_binding() is None


def test_input_validations(store: WorkspaceBlueprintStore) -> None:
    with pytest.raises(ValueError, match="workspace_id cannot be blank"):
        store.bind_blueprint("  ", "bp_1", "Team A")

    with pytest.raises(ValueError, match="blueprint_id cannot be blank"):
        store.bind_blueprint("ws_1", "  ", "Team A")

    with pytest.raises(ValueError, match="team_name cannot be blank"):
        store.bind_blueprint("ws_1", "bp_1", "  ")


def test_concurrent_bind_and_resolve(store: WorkspaceBlueprintStore) -> None:
    def _worker(idx: int) -> None:
        ws_id = f"ws_worker_{idx}"
        store.bind_blueprint(
            workspace_id=ws_id,
            blueprint_id=f"bp_{idx}",
            team_name=f"Team {idx}",
            auto_reuse_policy=AutoReusePolicy.ALWAYS_REUSE,
        )
        res = store.resolve_blueprint(ws_id)
        assert res.binding is not None
        store.record_usage(ws_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_worker, i) for i in range(24)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert len(store.list_bindings()) == 24
