# hitl_denial_events/

## Overview

Human-in-the-Loop (HITL) denial events and workflow coordination.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Human-in-the-Loop (HITL) denial events and workflow coordination | ✅ |
| dispatcher.py | Core | Event dispatcher for human-in-the-loop denial and confirmation lifecycles — Core dispatcher emitting explicit tool_result events on manual denials and coordinating the halt vs resume workflow. | ✅ |
| policy_evaluator.py | Core | Policy evaluation logic for all-tools-denied scenarios — Decision component configuring whether a full denial terminates the loop or feeds denial reasons back to the model for another reasoning cycle. | ✅ |
| types.py | Core | Domain types and events for Human-in-the-Loop (HITL) denial lifecycle — Core security primitive ensuring manual denials emit proper tool_result events with custom reasons and support configurable halt vs resume workflows. | ✅ |
