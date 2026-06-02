import pytest
from pydantic import ValidationError

from myrm_agent_harness.toolkits.interaction.ask_question import (
    AskQuestionInput,
    AskQuestionTool,
    OptionItem,
    QuestionItem,
)


@pytest.mark.asyncio
async def test_ask_question_tool_basic():
    async def mock_callback(form: AskQuestionInput) -> str:
        return "User skipped the clarification."

    tool = AskQuestionTool(callback=mock_callback)

    assert tool.name == "ask_question_tool"

    result = await tool._arun(
        questions=[
            {
                "id": "q1",
                "prompt": "What is your favorite color?",
                "options": [
                    {"id": "red", "label": "Red"},
                    {"id": "blue", "label": "Blue"},
                ],
            }
        ]
    )

    assert result == "User skipped the clarification."


@pytest.mark.asyncio
async def test_ask_question_tool_title():
    async def mock_callback(form: AskQuestionInput) -> str:
        assert form.title == "My Custom Title"
        return "Custom response"

    tool = AskQuestionTool(callback=mock_callback)

    result = await tool._arun(
        title="My Custom Title",
        questions=[
            {
                "id": "q1",
                "prompt": "Question 1",
                "options": [
                    {"id": "o1", "label": "Option 1"},
                    {"id": "o2", "label": "Option 2"},
                ],
                "allow_multiple": True,
            }
        ],
    )

    assert result == "Custom response"


@pytest.mark.asyncio
async def test_ask_question_tool_validation_error():
    async def mock_callback(form: AskQuestionInput) -> str:
        return "Should not reach here"

    tool = AskQuestionTool(callback=mock_callback)

    with pytest.raises(Exception):
        await tool._arun(
            questions=[
                {
                    "id": "q1",
                    "options": [
                        {"id": "o1", "label": "Option 1"},
                    ],
                }
            ]
        )


@pytest.mark.asyncio
async def test_multi_question_form():
    """Multiple questions are passed through correctly."""

    async def mock_callback(form: AskQuestionInput) -> str:
        assert len(form.questions) == 3
        assert form.questions[0].id == "q1"
        assert form.questions[1].allow_multiple is True
        assert form.questions[2].options == []
        return "multi-ok"

    tool = AskQuestionTool(callback=mock_callback)
    result = await tool._arun(
        questions=[
            {"id": "q1", "prompt": "Single choice?", "options": [{"id": "a", "label": "A"}]},
            {"id": "q2", "prompt": "Multi choice?", "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}], "allow_multiple": True},
            {"id": "q3", "prompt": "Open ended?"},
        ],
    )
    assert result == "multi-ok"


@pytest.mark.asyncio
async def test_open_ended_question():
    """Questions without options work as open-ended questions."""

    async def mock_callback(form: AskQuestionInput) -> str:
        q = form.questions[0]
        assert q.options == []
        assert q.allow_multiple is False
        return "open-ended-ok"

    tool = AskQuestionTool(callback=mock_callback)
    result = await tool._arun(
        questions=[{"id": "q1", "prompt": "Describe your issue in detail."}],
    )
    assert result == "open-ended-ok"


@pytest.mark.asyncio
async def test_option_with_description():
    """OptionItem.description field is correctly parsed."""

    async def mock_callback(form: AskQuestionInput) -> str:
        opt = form.questions[0].options[0]
        assert opt.description == "Detailed explanation"
        return "desc-ok"

    tool = AskQuestionTool(callback=mock_callback)
    result = await tool._arun(
        questions=[
            {
                "id": "q1",
                "prompt": "Choose",
                "options": [{"id": "o1", "label": "Option 1", "description": "Detailed explanation"}],
            }
        ],
    )
    assert result == "desc-ok"


def test_sync_run_raises():
    """Synchronous _run must raise NotImplementedError."""

    async def mock_callback(form: AskQuestionInput) -> str:
        return "nope"

    tool = AskQuestionTool(callback=mock_callback)
    with pytest.raises(NotImplementedError):
        tool._run(questions=[{"id": "q1", "prompt": "test"}])


def test_empty_questions_validation():
    """Empty questions list must fail Pydantic validation."""
    with pytest.raises(ValidationError):
        AskQuestionInput(questions=[])


def test_pydantic_models_direct():
    """Direct construction of Pydantic models for schema correctness."""
    opt = OptionItem(id="o1", label="Label", description=None)
    assert opt.id == "o1"
    assert opt.description is None

    q = QuestionItem(id="q1", prompt="Hello?", options=[opt], allow_multiple=False)
    assert q.prompt == "Hello?"
    assert len(q.options) == 1

    form = AskQuestionInput(title="Test Form", questions=[q])
    assert form.title == "Test Form"

    form_no_title = AskQuestionInput(questions=[q])
    assert form_no_title.title is None
