"""Interactive Clarification Tool.

[INPUT]

[OUTPUT]
- AskQuestionTool: Tool for asking structured multiple-choice or open-ended questions.
- AskQuestionInput, QuestionItem, OptionItem: Pydantic schemas for structured forms.

[POS]
Provides a standardized way for agents to interactively query the user via structured forms.
"""

from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr


class OptionItem(BaseModel):
    """An option item for a multiple-choice question."""

    id: str = Field(
        description="Unique identifier for this option. Use short, snake_case strings."
    )
    label: str = Field(description="Display text for this option.")
    description: str | None = Field(
        default=None,
        description="Optional detailed explanation of what this option means.",
    )


class QuestionItem(BaseModel):
    """A structured question item."""

    id: str = Field(
        description="Unique identifier for this question. Use short, snake_case strings."
    )
    prompt: str = Field(description="The question prompt to present to the user.")
    options: list[OptionItem] = Field(
        default_factory=list,
        description="Available choices for this question. Leave empty for a purely open-ended question.",
    )
    allow_multiple: bool = Field(
        default=False,
        description="If true, the user can select multiple options.",
    )


class AskQuestionInput(BaseModel):
    """Input schema for the ask_question tool."""

    title: str | None = Field(
        default=None, description="Optional title for the clarification form."
    )
    questions: list[QuestionItem] = Field(
        min_length=1,
        description="A list of one or more clarifying questions to ask the user.",
    )


class AskQuestionTool(BaseTool):
    """Tool for asking the user structured questions."""

    name: str = "ask_question_tool"
    tags: list[str] = ["interactive"]
    description: str = (
        "Ask the user one or more clarifying questions. Use this when the request is ambiguous, "
        "or when you need to confirm intent, choose between options, or gather missing details "
        "before proceeding. You can provide predefined options with descriptions, or leave options "
        "empty for open-ended questions.\n"
        "CRITICAL: You can only call this tool ONCE per turn. If you have multiple questions, "
        "put ALL of them in the `questions` list of a SINGLE tool call. Do NOT call this tool "
        "multiple times in parallel."
    )
    args_schema: type[BaseModel] = AskQuestionInput

    _callback: Callable[[AskQuestionInput], Awaitable[str]] = PrivateAttr()

    def __init__(self, callback: Callable[[AskQuestionInput], Awaitable[str]]) -> None:
        """Initialize the tool with a callback."""

        super().__init__()
        self._callback = callback

    async def _arun(self, **kwargs: object) -> str:
        input_data = AskQuestionInput.model_validate(kwargs)
        return await self._callback(input_data)

    def _run(self, **kwargs: object) -> str:
        raise NotImplementedError("AskQuestionTool only supports async execution.")
