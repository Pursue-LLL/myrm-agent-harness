# core/events/

## Overview
Framework-agnostic event type definitions. Provides AgentEventType enum, AgentStreamEvent wrapper, and THINKING_TAG_NAMES constant.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports event types and defines THINKING_TAG_NAMES. | ✅ |
| types.py | Core | AgentEventType (StrEnum), AgentStreamEvent (dataclass with dict-like access), ContextBudgetSnapshot, ApprovalInterceptedEventData. | ✅ |

## Key Dependencies

- No internal dependencies (foundation layer)
