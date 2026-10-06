"""Unit tests for Artifact-Centric Agent Loop & Dynamic Intent Tracking Engine (Item 26)."""

import pytest

from myrm_agent_harness.runtime.context.artifact_centric_loop import (
    ActorRole,
    ArtifactLifecycleState,
    ArtifactType,
    DynamicIntentTracker,
    IntentDeltaKind,
    LivingArtifactSnapshot,
    LivingArtifactStateMachine,
    WorkingSceneHydrationPayload,
    WorkingSceneHydrator,
)


def test_artifact_registration_and_version_progression() -> None:
    """Verifies artifact registration, version increments, and lifecycle state transitions."""
    sm = LivingArtifactStateMachine()

    snap1: LivingArtifactSnapshot = sm.register_artifact(
        artifact_id="art-001",
        artifact_type=ArtifactType.CODE,
        name="server.py",
        initial_content="print('v1')",
        actor=ActorRole.AGENT,
    )
    assert snap1.version == 1
    assert snap1.state == ArtifactLifecycleState.DRAFT
    assert snap1.content == "print('v1')"

    # Duplicate registration fails
    with pytest.raises(ValueError, match="already registered"):
        sm.register_artifact("art-001", ArtifactType.CODE, "server.py", "duplicate")

    # Update content increments version and preserves artifact type
    snap2 = sm.update_content(
        artifact_id="art-001",
        new_content="print('v2')",
        actor=ActorRole.USER,
        new_state=ArtifactLifecycleState.IN_REVIEW,
    )
    assert snap2.version == 2
    assert snap2.state == ArtifactLifecycleState.IN_REVIEW
    assert snap2.last_actor == ActorRole.USER
    assert snap2.content_hash != snap1.content_hash

    # Transition state without content modification
    snap3 = sm.transition_state(
        artifact_id="art-001",
        target_state=ArtifactLifecycleState.ACCEPTED,
        actor=ActorRole.USER,
    )
    assert snap3.version == 3
    assert snap3.state == ArtifactLifecycleState.ACCEPTED
    assert snap3.content == "print('v2')"


def test_dynamic_intent_tracking_chain() -> None:
    """Verifies intent delta recording and human action discrimination."""
    tracker = DynamicIntentTracker(session_id="sess-xyz")

    d1 = tracker.record_delta(
        artifact_id="art-001",
        actor=ActorRole.AGENT,
        action=IntentDeltaKind.PROMPT_DIRECTIVE,
        semantic_intent="Initial code generation",
    )
    assert d1.actor == ActorRole.AGENT

    d2 = tracker.record_delta(
        artifact_id="art-001",
        actor=ActorRole.USER,
        action=IntentDeltaKind.ELEMENT_SELECT,
        target_ref="lines 10-15",
        semantic_intent="User highlighted retry loop",
    )
    assert d2.actor == ActorRole.USER

    d3 = tracker.record_delta(
        artifact_id="art-001",
        actor=ActorRole.USER,
        action=IntentDeltaKind.ANNOTATION,
        target_ref="function foo()",
        semantic_intent="Add exponential backoff",
        payload_diff="+ retry_delay *= 2",
    )
    assert d3.action == IntentDeltaKind.ANNOTATION

    deltas = tracker.get_recent_deltas(limit=10)
    assert len(deltas) == 3

    human_deltas = tracker.get_unacknowledged_human_deltas()
    assert len(human_deltas) == 2
    assert all(d.actor == ActorRole.USER for d in human_deltas)


def test_working_scene_hydrator() -> None:
    """Verifies that WorkingSceneHydrator produces lossless, structured context for next turn."""
    sm = LivingArtifactStateMachine()
    sm.register_artifact(
        artifact_id="arch-doc",
        artifact_type=ArtifactType.DIAGRAM,
        name="architecture.dot",
        initial_content="digraph G { Client -> Gateway -> Service; }",
        actor=ActorRole.AGENT,
    )
    sm.register_artifact(
        artifact_id="api-spec",
        artifact_type=ArtifactType.DOCUMENT,
        name="openapi.yaml",
        initial_content="openapi: 3.0.0\ninfo:\n  title: Myrm API",
        actor=ActorRole.AGENT,
    )

    tracker = DynamicIntentTracker(session_id="sess-hydra")
    tracker.record_delta(
        artifact_id="arch-doc",
        actor=ActorRole.USER,
        action=IntentDeltaKind.MANUAL_EDIT,
        target_ref="Gateway",
        semantic_intent="User added WAF proxy node",
        payload_diff="+ Gateway -> WAF -> Service",
    )

    payload: WorkingSceneHydrationPayload = WorkingSceneHydrator.hydrate_scene(sm, tracker)

    assert payload.active_artifacts_count == 2
    assert payload.pending_human_actions_count == 1
    assert "Hydrated 2 active artifact(s)" in payload.hydration_summary
    assert "<!-- LIVING-ARTIFACT WORKING SCENE (Auto-Hydrated by Harness) -->" in payload.formatted_context_block
    assert "architecture.dot" in payload.formatted_context_block
    assert "openapi.yaml" in payload.formatted_context_block
    assert "👤 User" in payload.formatted_context_block
    assert "User added WAF proxy node" in payload.formatted_context_block


def test_working_scene_hydrator_empty_scene() -> None:
    """Verifies hydration handles empty artifact and delta states gracefully."""
    sm = LivingArtifactStateMachine()
    tracker = DynamicIntentTracker(session_id="sess-empty")

    payload = WorkingSceneHydrator.hydrate_scene(sm, tracker)
    assert payload.active_artifacts_count == 0
    assert payload.pending_human_actions_count == 0
    assert "(None registered)" in payload.formatted_context_block
    assert "(No recent interaction deltas)" in payload.formatted_context_block


def test_artifact_rollback_and_history() -> None:
    """Verifies rollback creates a new version head restoring past content."""
    sm = LivingArtifactStateMachine()
    sm.register_artifact(
        artifact_id="art-rb",
        artifact_type=ArtifactType.CODE,
        name="main.py",
        initial_content="base code",
        actor=ActorRole.AGENT,
    )
    sm.update_content("art-rb", "buggy code v2", actor=ActorRole.AGENT)
    sm.update_content("art-rb", "broken code v3", actor=ActorRole.AGENT)

    current = sm.get_latest_snapshot("art-rb")
    assert current.version == 3

    # Rollback to version 1
    rolled_back = sm.rollback_to_version("art-rb", target_version=1, actor=ActorRole.USER)
    assert rolled_back.version == 4
    assert rolled_back.content == "base code"
    assert rolled_back.last_actor == ActorRole.USER

    # Rollback to invalid version raises ValueError
    with pytest.raises(ValueError, match="does not exist"):
        sm.rollback_to_version("art-rb", target_version=99, actor=ActorRole.USER)

    # Unknown artifact raises KeyError
    with pytest.raises(KeyError):
        sm.rollback_to_version("unknown-art", target_version=1, actor=ActorRole.USER)
