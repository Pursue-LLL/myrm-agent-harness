"""Unit tests for Hidden Goal & Rubric Context Preamble Injection Engine (Item 28)."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.runtime.context.hidden_goal_rubric_preamble import (
    GoalRubricContext,
    GoalStatus,
    HiddenGoalRubricPreamble,
    PreambleInjectionPolicy,
    RubricSource,
)


def test_format_preamble_block_escapes_and_structures() -> None:
    """Verifies that preamble rendering applies safe HTML escaping and structured XML tags."""
    ctx = GoalRubricContext(
        goal_id="g-101",
        objective="Refactor Auth <script>alert(1)</script>",
        criteria="1. Unit tests pass & latency < 50ms\n2. Zero regressions",
        status=GoalStatus.ACTIVE,
        status_note="In progress with token limit",
        rubric_source=RubricSource.GOAL,
    )

    block = HiddenGoalRubricPreamble.format_preamble_block(ctx)
    assert "<goal_objective>" in block
    assert "Refactor Auth &lt;script&gt;alert(1)&lt;/script&gt;" in block
    assert "<acceptance_criteria source='goal'>" in block
    assert "latency &lt; 50ms" in block
    assert "Status: ACTIVE (In progress with token limit)" in block
    assert "without invoking `get_goal` or `get_rubric`" in block


def test_first_turn_injection_after_system_message() -> None:
    """Verifies first-turn automatic injection places preamble right after SystemMessage."""
    ctx = GoalRubricContext(
        goal_id="g-first",
        objective="Analyze logs",
        criteria="Find error root cause",
    )

    messages = [
        SystemMessage(content="You are an autonomous engineering assistant."),
        HumanMessage(content="Please investigate crash incident."),
    ]

    injected = HiddenGoalRubricPreamble.inject_preamble_message(messages, ctx)
    assert len(injected) == 3

    # Position 0: SystemMessage
    assert isinstance(injected[0], SystemMessage)
    # Position 1: Hidden preamble HumanMessage
    assert isinstance(injected[1], HumanMessage)
    assert injected[1].additional_kwargs.get("is_hidden_preamble") is True
    assert injected[1].additional_kwargs.get("lc_source") == "goal_state"
    assert "<goal_objective>\nAnalyze logs\n</goal_objective>" in str(injected[1].content)
    # Position 2: Original User message
    assert injected[2].content == "Please investigate crash incident."


def test_mid_turn_goal_update_supersedes_existing_notices() -> None:
    """Verifies that updating goal replaces prior notices with superseded marks and appends fresh notice."""
    ctx1 = GoalRubricContext(
        goal_id="g-01",
        objective="Step 1: Write code",
        criteria="Pass tests",
    )
    ctx2 = GoalRubricContext(
        goal_id="g-01",
        objective="Step 2: Deploy service",
        criteria="Zero 5xx errors",
        status=GoalStatus.ACTIVE,
    )

    initial_history = [
        SystemMessage(content="System"),
        HumanMessage(content="Begin"),
    ]

    # First turn injection
    turn1_msgs = HiddenGoalRubricPreamble.inject_preamble_message(initial_history, ctx1)
    assert len(turn1_msgs) == 3

    # Add agent response and user steer
    turn1_msgs.append(AIMessage(content="Code written."))
    turn1_msgs.append(HumanMessage(content="Now deploy it."))

    # Second turn injection with updated goal
    turn2_msgs = HiddenGoalRubricPreamble.inject_preamble_message(turn1_msgs, ctx2)

    # Previous notice should be superseded
    superseded_found = False
    fresh_found = False

    for msg in turn2_msgs:
        kw = getattr(msg, "additional_kwargs", {})
        if kw.get("lc_source") == "goal_state_superseded":
            superseded_found = True
            assert "Stale goal context superseded" in str(msg.content)
        elif kw.get("lc_source") == "goal_state":
            fresh_found = True
            assert "Step 2: Deploy service" in str(msg.content)

    assert superseded_found is True
    assert fresh_found is True


def test_filter_for_user_transcript_purges_preambles() -> None:
    """Verifies that filter_for_user_transcript strips all internal goal notices for clean UI rendering."""
    custom_policy = PreambleInjectionPolicy(
        hide_from_user_transcript=True,
        lc_source_tag="custom_goal_source",
        superseded_source_tag="custom_superseded_source",
    )
    ctx = GoalRubricContext(
        goal_id="g-clean",
        objective="Confidential objective",
        criteria="Confidential rubric",
    )

    messages = [
        SystemMessage(content="System instructions"),
        HumanMessage(content="User query"),
    ]

    with_preamble = HiddenGoalRubricPreamble.inject_preamble_message(messages, ctx, policy=custom_policy)
    assert len(with_preamble) == 3
    assert with_preamble[1].additional_kwargs.get("lc_source") == "custom_goal_source"

    clean_user_transcript = HiddenGoalRubricPreamble.filter_for_user_transcript(with_preamble, policy=custom_policy)
    assert len(clean_user_transcript) == 2
    assert all(not HiddenGoalRubricPreamble.is_hidden_goal_message(m, policy=custom_policy) for m in clean_user_transcript)
    assert clean_user_transcript[0].content == "System instructions"
    assert clean_user_transcript[1].content == "User query"


def test_goal_context_fingerprint_consistency() -> None:
    """Verifies that context fingerprints are deterministic and capture attribute mutations."""
    ctx1 = GoalRubricContext(goal_id="g1", objective="Obj", criteria="Crit")
    ctx2 = GoalRubricContext(goal_id="g1", objective="Obj", criteria="Crit")
    ctx3 = GoalRubricContext(goal_id="g1", objective="Obj", criteria="Crit", status=GoalStatus.BLOCKED)

    assert ctx1.fingerprint == ctx2.fingerprint
    assert ctx1.fingerprint != ctx3.fingerprint
