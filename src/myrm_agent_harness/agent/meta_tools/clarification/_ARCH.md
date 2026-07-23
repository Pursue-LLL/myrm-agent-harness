# clarification/

## Overview

Agent meta-tools for structured HITL clarification (`ask_question_tool`). Schemas and LangChain adapter live here; LangGraph interrupt binding is injected by server `tool_setup.py` when `_should_mount_ask_question_tool` returns true (interactive `web_chat` sessions only).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `ask_question.py` | Core | Pydantic schemas: AskQuestionInput, QuestionItem, OptionItem | ✅ |
| `clarification_agent_tools.py` | Core | AskQuestionTool + create_ask_question_tool factory | ✅ |
| `__init__.py` | Package | Public exports | ✅ |

## Key Dependencies

- Server: `tool_setup._setup_clarification_tools` injects interrupt when product `structured_clarify` is ON and mount policy allows (`web_chat`, not unattended, not fast search). Interrupt payload `{type, form}` uses `AskQuestionInput.model_dump()` including `requires_confirmation`.
- Frontend: `clarification_required` SSE → `toolsProgressEvents` → `ClarificationInput`; `requires_confirmation=true` renders amber risk emphasis.
- Harness: `ClarificationGuardMiddleware` enforces one `ask_question_tool` call per turn (blocks duplicates and coexisting tools).
- Harness: `DelegationCapabilityManifest.leaf_blocked_tools` strips `ask_question_tool` from leaf subagents (HITL must stay on parent/web thread).
