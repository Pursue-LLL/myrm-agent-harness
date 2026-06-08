from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.goals.goal_interceptor import intercept_goal_and_plan
from myrm_agent_harness.agent.goals.types import Goal, GoalStatus

_MODULE = "myrm_agent_harness.agent.goals.goal_interceptor"


def _make_goal(goal_id: str = "g1", session_id: str = "s1") -> Goal:
    return Goal(
        goal_id=goal_id,
        session_id=session_id,
        objective="Write a scraper",
        status=GoalStatus.ACTIVE,
    )


@pytest.fixture
def goal_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.get_active_goal.return_value = _make_goal()
    return provider


@pytest.fixture
def storage_provider() -> MagicMock:
    return MagicMock()


@pytest.fixture
def llm() -> MagicMock:
    return MagicMock()


# --------------------------------------------------------------------- #
# Happy paths
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_active_goal_returns_early(goal_provider, llm, storage_provider):
    goal_provider.get_active_goal.return_value = None

    await intercept_goal_and_plan(
        goal_provider, "s1", "do stuff", llm, storage_provider
    )

    goal_provider.update_status.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_MODULE}.PlannerStorage")
async def test_existing_plan_skips_generation(
    mock_storage_cls,
    goal_provider,
    llm,
    storage_provider,
):
    mock_storage_cls.return_value.load_plan = AsyncMock(return_value={"phases": []})

    await intercept_goal_and_plan(
        goal_provider, "s1", "do stuff", llm, storage_provider
    )

    goal_provider.update_status.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_MODULE}.interrupt")
@patch(f"{_MODULE}.PlannerAgent")
@patch(f"{_MODULE}.PlannerStorage")
async def test_generates_plan_and_suspends(
    mock_storage_cls,
    mock_agent_cls,
    mock_interrupt,
    goal_provider,
    llm,
    storage_provider,
):
    mock_storage_cls.return_value.load_plan = AsyncMock(return_value=None)
    mock_agent_cls.return_value.create_plan = AsyncMock()

    await intercept_goal_and_plan(
        goal_provider, "s1", "do stuff", llm, storage_provider
    )

    mock_agent_cls.return_value.create_plan.assert_awaited_once()
    goal_provider.update_status.assert_awaited_once_with(
        "g1", GoalStatus.PENDING_APPROVAL
    )
    mock_interrupt.assert_called_once()
    payload = mock_interrupt.call_args[0][0]
    assert payload["type"] == "goal_approval_required"
    assert payload["goal_id"] == "g1"


# --------------------------------------------------------------------- #
# Failure & rollback paths
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
@patch(f"{_MODULE}.PlannerAgent")
@patch(f"{_MODULE}.PlannerStorage")
async def test_plan_failure_rolls_back_to_cancelled(
    mock_storage_cls,
    mock_agent_cls,
    goal_provider,
    llm,
    storage_provider,
):
    mock_storage_cls.return_value.load_plan = AsyncMock(return_value=None)
    mock_agent_cls.return_value.create_plan = AsyncMock(
        side_effect=RuntimeError("LLM timeout"),
    )

    with pytest.raises(RuntimeError, match="plan generation failed"):
        await intercept_goal_and_plan(
            goal_provider, "s1", "do stuff", llm, storage_provider
        )

    goal_provider.update_status.assert_awaited_once_with("g1", GoalStatus.CANCELLED)


@pytest.mark.asyncio
@patch(f"{_MODULE}.PlannerAgent")
@patch(f"{_MODULE}.PlannerStorage")
async def test_plan_failure_rollback_also_fails(
    mock_storage_cls,
    mock_agent_cls,
    goal_provider,
    llm,
    storage_provider,
):
    """Even if the rollback itself fails, the original error still propagates."""
    mock_storage_cls.return_value.load_plan = AsyncMock(return_value=None)
    mock_agent_cls.return_value.create_plan = AsyncMock(
        side_effect=RuntimeError("LLM timeout"),
    )
    goal_provider.update_status = AsyncMock(
        side_effect=ConnectionError("DB unreachable"),
    )

    with pytest.raises(RuntimeError, match="plan generation failed"):
        await intercept_goal_and_plan(
            goal_provider, "s1", "do stuff", llm, storage_provider
        )

    goal_provider.update_status.assert_awaited_once_with("g1", GoalStatus.CANCELLED)


@pytest.mark.asyncio
@patch(f"{_MODULE}.PlannerAgent")
@patch(f"{_MODULE}.PlannerStorage")
async def test_plan_failure_preserves_exception_chain(
    mock_storage_cls,
    mock_agent_cls,
    goal_provider,
    llm,
    storage_provider,
):
    """The raised RuntimeError wraps the original cause via 'from e'."""
    original = ValueError("bad prompt")
    mock_storage_cls.return_value.load_plan = AsyncMock(return_value=None)
    mock_agent_cls.return_value.create_plan = AsyncMock(side_effect=original)

    with pytest.raises(RuntimeError) as exc_info:
        await intercept_goal_and_plan(
            goal_provider, "s1", "do stuff", llm, storage_provider
        )

    assert exc_info.value.__cause__ is original


# --------------------------------------------------------------------- #
# Multimodal query support
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
@patch(f"{_MODULE}.interrupt")
@patch(f"{_MODULE}.PlannerAgent")
@patch(f"{_MODULE}.PlannerStorage")
async def test_multimodal_query_forwarded_to_planner(
    mock_storage_cls,
    mock_agent_cls,
    mock_interrupt,
    goal_provider,
    llm,
    storage_provider,
):
    """Multimodal queries (list of content parts) are passed through to PlannerAgent."""
    mock_storage_cls.return_value.load_plan = AsyncMock(return_value=None)
    mock_agent_cls.return_value.create_plan = AsyncMock()

    multimodal_query = [
        {"type": "text", "text": "Plan from this whiteboard"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
    ]

    await intercept_goal_and_plan(
        goal_provider, "s1", multimodal_query, llm, storage_provider
    )

    mock_agent_cls.return_value.create_plan.assert_awaited_once()
    task_content = mock_agent_cls.return_value.create_plan.call_args[0][0]
    # Should be a list (multimodal), not a plain string
    assert isinstance(task_content, list)
    # First part is the preamble text
    assert task_content[0]["type"] == "text"
    assert "Goal Objective:" in task_content[0]["text"]
    # Original content parts are preserved after preamble
    assert task_content[1] == {"type": "text", "text": "Plan from this whiteboard"}
    assert task_content[2]["type"] == "image_url"
