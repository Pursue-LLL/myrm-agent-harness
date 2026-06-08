# guardrails/

## Overview
OAP-style pre-tool-call guardrail chain. `GuardrailMiddleware` evaluates each tool call against registered `GuardrailProvider` implementations before execution.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports guardrail middleware and core types | — |
| core.py | Core | GuardrailRequest, GuardrailDecision, GuardrailProvider protocol | — |
| middleware.py | Core | GuardrailMiddleware — LangChain AgentMiddleware hook | — |

| Submodule | Description |
|-----------|-------------|
| providers/ | Concrete guardrail providers. See [providers/_ARCH.md](providers/_ARCH.md). |

## Module Dependencies

- `langchain.agents.middleware::AgentMiddleware`
- `langgraph.prebuilt.tool_node::ToolCallRequest`
