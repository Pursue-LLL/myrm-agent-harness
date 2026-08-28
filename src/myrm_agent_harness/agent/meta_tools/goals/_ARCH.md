# meta_tools/goals/

## Overview
LangChain tool surface for the Goal engine. Domain logic lives in `agent/goals/`; this package only exposes LLM-callable tools bound to a `GoalProvider`.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports goal tool factories | ✅ |
| goal_agent_tools.py | Core | complete_goal_tool, create_goal_tools | ✅ |

## Module Dependencies

- `agent.goals.protocols::GoalProvider` (POS: Goal state access contract)
- `agent.goals.types::GoalStatus` (POS: Goal status enum)

## Tool Specifications

- `complete_goal_tool`: Marks active goal as complete after verifying all acceptance criteria. Includes idempotency protection if the goal is already in `COMPLETE` status.
