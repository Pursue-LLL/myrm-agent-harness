# clarification/

## Overview

Agent meta-tools for structured HITL clarification (`ask_question_tool`). Schemas and LangChain adapter live here; LangGraph interrupt binding is injected by server `tool_setup.py`.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `ask_question.py` | Core | Pydantic schemas: AskQuestionInput, QuestionItem, OptionItem | ✅ |
| `clarification_agent_tools.py` | Core | AskQuestionTool + create_ask_question_tool factory | ✅ |
| `__init__.py` | Package | Public exports | ✅ |

## Key Dependencies

- Server: `tool_setup._setup_clarification_tools` injects interrupt callback
- Frontend: `clarification_required` SSE → clarification form UI
