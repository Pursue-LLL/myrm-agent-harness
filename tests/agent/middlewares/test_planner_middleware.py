import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.planner_middleware import planner_middleware
from myrm_agent_harness.agent.sub_agents.planner.schemas import (
    DecisionRecord,
    Plan,
    PlanStep,
)


@pytest.fixture
def sample_plan():
    return Plan(
        goal="Test goal",
        reasoning="Test reasoning",
        steps=[
            PlanStep(
                step_id="step_1",
                description="Test step",
                expected_output="Test output",
                status="in_progress",
            )
        ],
        current_step_id="step_1",
        decisions=[
            DecisionRecord(
                id="d1", topic="DB", decision="Decision 1: Use SQLite", rationale=""
            ),
            DecisionRecord(
                id="d2", topic="UI", decision="Decision 2: Use React", rationale=""
            ),
        ],
    )


@pytest.mark.asyncio
async def test_planner_middleware_injects_key_findings_to_human_message(sample_plan):
    async def mock_get_plan(workspace_root):
        return sample_plan

    middleware = planner_middleware(mock_get_plan)

    # Create a mock handler
    async def mock_handler(req: ModelRequest):
        return req

    # Request with a HumanMessage at the end
    messages = [
        SystemMessage(content="Initial system prompt"),
        HumanMessage(content="User input"),
    ]
    request = ModelRequest(messages=messages, model="test_model")

    # Run middleware
    response = await middleware.awrap_model_call(request, mock_handler)

    new_messages = response.messages
    assert len(new_messages) == 2

    assert isinstance(new_messages[0], SystemMessage)
    assert new_messages[0].content == "Initial system prompt"

    last_msg = new_messages[-1]
    assert isinstance(last_msg, HumanMessage)
    assert "User input" in last_msg.content
    assert "[SYSTEM INSTRUCTION]" in last_msg.content
    assert "##  Goal Blueprint (Static)" in last_msg.content
    assert "ANTI-DRIFT REMINDER" in last_msg.content
    assert "<architectural_decisions>" in last_msg.content
    assert "Decision 1: Use SQLite" in last_msg.content


@pytest.mark.asyncio
async def test_planner_middleware_injects_key_findings_to_list_content(sample_plan):
    async def mock_get_plan(workspace_root):
        return sample_plan

    middleware = planner_middleware(mock_get_plan)

    async def mock_handler(req: ModelRequest):
        return req

    # Request with a HumanMessage containing a list
    messages = [HumanMessage(content=[{"type": "text", "text": "User input"}])]
    request = ModelRequest(messages=messages, model="test_model")

    response = await middleware.awrap_model_call(request, mock_handler)
    new_messages = response.messages

    last_msg = new_messages[-1]
    assert isinstance(last_msg, HumanMessage)
    assert isinstance(last_msg.content, list)
    assert len(last_msg.content) == 2
    assert last_msg.content[0]["text"] == "User input"
    assert "[SYSTEM INSTRUCTION]" in last_msg.content[1]["text"]
    assert "Decision 2: Use React" in last_msg.content[1]["text"]


@pytest.fixture
def multi_step_plan():
    return Plan(
        goal="Refactor authentication system",
        reasoning="Need to modernize auth",
        steps=[
            PlanStep(step_id="step_1", description="Analyze existing auth code", expected_output="Analysis report", status="completed"),
            PlanStep(step_id="step_2", description="Rewrite JWT middleware", expected_output="New JWT module", status="skipped"),
            PlanStep(step_id="step_3", description="Add refresh token rotation", expected_output="Token rotation endpoint", status="in_progress"),
            PlanStep(step_id="step_4", description="Update user sessions", expected_output="Session management", status="pending"),
            PlanStep(step_id="step_5", description="Integration tests", expected_output="All tests pass", status="pending"),
        ],
        current_step_id="step_3",
    )


@pytest.mark.asyncio
async def test_planner_middleware_progress_overview(multi_step_plan):
    async def mock_get_plan(workspace_root):
        return multi_step_plan

    middleware = planner_middleware(mock_get_plan)

    async def mock_handler(req: ModelRequest):
        return req

    messages = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="Continue working"),
    ]
    request = ModelRequest(messages=messages, model="test_model")

    response = await middleware.awrap_model_call(request, mock_handler)
    last_msg = response.messages[-1]

    assert "Progress: [2/5]" in last_msg.content
    assert "step_1 done" in last_msg.content
    assert "step_2 skip" in last_msg.content
    assert "step_3 [current]" in last_msg.content
    assert "step_4" in last_msg.content
    assert "step_5" in last_msg.content


@pytest.mark.asyncio
async def test_planner_middleware_progress_first_step():
    """Progress shows 0/N when no steps completed yet."""
    plan = Plan(
        goal="Build feature",
        reasoning="New feature",
        steps=[
            PlanStep(step_id="s1", description="Step 1", expected_output="Output 1", status="pending"),
            PlanStep(step_id="s2", description="Step 2", expected_output="Output 2", status="pending"),
        ],
        current_step_id="s1",
    )

    async def mock_get_plan(workspace_root):
        return plan

    middleware = planner_middleware(mock_get_plan)

    async def mock_handler(req: ModelRequest):
        return req

    messages = [HumanMessage(content="Start")]
    request = ModelRequest(messages=messages, model="test_model")

    response = await middleware.awrap_model_call(request, mock_handler)
    last_msg = response.messages[-1]

    assert "Progress: [0/2]" in last_msg.content
    assert "s1 [current]" in last_msg.content
    assert "s2" in last_msg.content


@pytest.mark.asyncio
async def test_planner_middleware_no_human_message(sample_plan):
    async def mock_get_plan(workspace_root):
        return sample_plan

    middleware = planner_middleware(mock_get_plan)

    async def mock_handler(req: ModelRequest):
        return req

    # Request with no HumanMessage
    messages = [
        SystemMessage(content="Initial system prompt"),
        AIMessage(content="AI response"),
    ]
    request = ModelRequest(messages=messages, model="test_model")

    response = await middleware.awrap_model_call(request, mock_handler)
    new_messages = response.messages

    # Should append a new HumanMessage at the end
    assert len(new_messages) == 3
    last_msg = new_messages[-1]
    assert isinstance(last_msg, HumanMessage)
    assert "[SYSTEM INSTRUCTION]" in last_msg.content
    assert "Decision 1: Use SQLite" in last_msg.content


@pytest.mark.asyncio
async def test_planner_middleware_injects_risk_for_medium_and_high():
    """Verify that risk_level medium/high is shown in blueprint, low/None is hidden."""
    plan = Plan(
        goal="Test risk rendering",
        reasoning="Testing",
        steps=[
            PlanStep(step_id="s1", description="Safe work", expected_output="done", risk_level="low"),
            PlanStep(step_id="s2", description="Multi-file edit", expected_output="done", risk_level="medium"),
            PlanStep(step_id="s3", description="Prod migration", expected_output="done", risk_level="high"),
            PlanStep(step_id="s4", description="Unknown risk", expected_output="done", risk_level=None),
        ],
        current_step_id="s1",
    )

    async def mock_get_plan(workspace_root):
        return plan

    middleware = planner_middleware(mock_get_plan)

    async def mock_handler(req: ModelRequest):
        return req

    messages = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="User message"),
    ]
    request = ModelRequest(messages=messages, model="test_model")

    response = await middleware.awrap_model_call(request, mock_handler)
    last_msg = response.messages[-1]
    assert isinstance(last_msg, HumanMessage)
    blueprint = last_msg.content

    assert "**Risk:** medium" in blueprint
    assert "**Risk:** high" in blueprint
    assert blueprint.count("**Risk:**") == 2
