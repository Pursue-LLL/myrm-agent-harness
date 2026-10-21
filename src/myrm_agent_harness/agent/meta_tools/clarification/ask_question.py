"""Structured clarification form schemas for agent HITL.

[INPUT]
- None

[OUTPUT]
- AskQuestionInput, QuestionItem, OptionItem: Pydantic schemas for structured forms.

[POS]
Schema SSOT for ask_question_tool. LangChain adapter lives in clarification_agent_tools.py.
"""

from pydantic import BaseModel, Field


class OptionItem(BaseModel):
    """An option item for a multiple-choice question."""

    id: str = Field(description="Unique identifier for this option. Use short, snake_case strings.")
    label: str = Field(description="Display text for this option.")
    description: str | None = Field(
        default=None,
        description="Optional detailed explanation of what this option means.",
    )


class QuestionItem(BaseModel):
    """A structured question item."""

    id: str = Field(description="Unique identifier for this question. Use short, snake_case strings.")
    prompt: str = Field(description="The question prompt to present to the user.")
    options: list[OptionItem] = Field(
        default_factory=list,
        description="Discrete choices for this question (minimum 2 recommended when applicable). Leave empty only for open-ended text input.",
    )
    allow_multiple: bool = Field(
        default=False,
        description="Whether the user can select multiple options. Set to true for multi-select checklists.",
    )


class AskQuestionInput(BaseModel):
    """Input schema for the ask_question tool."""

    title: str | None = Field(default=None, description="Optional title for the clarification form.")
    requires_confirmation: bool = Field(
        default=False,
        description=(
            "Set to true before irreversible, destructive, or high-risk operations to request explicit user sign-off."
        ),
    )
    context: str | None = Field(
        default=None,
        description="Optional background explaining why clarification is needed.",
    )
    questions: list[QuestionItem] = Field(
        min_length=1,
        description="List of clarifying questions (minimum 1). Include all questions in this single call.",
    )
