# core/events/

## Overview
Framework-agnostic event type definitions. Provides AgentEventType enum, AgentStreamEvent wrapper, and THINKING_TAG_NAMES constant.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports event types and defines THINKING_TAG_NAMES. | ✅ |
| types.py | Core | AgentEventType (StrEnum), AgentStreamEvent (dataclass with dict-like access), ContextBudgetSnapshot (incl. optional `turn_count` for GUI preflight, emitted only when checkpoint messages are readable), ApprovalInterceptedEventData. | ✅ |

## Key Dependencies

- No internal dependencies (foundation layer)
