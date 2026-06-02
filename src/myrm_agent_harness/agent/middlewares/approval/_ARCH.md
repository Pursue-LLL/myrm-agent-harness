# approval/

## Overview
Tool approval subsystem — Human-in-the-Loop approval flow.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Tool approval subsystem — Human-in-the-Loop approval flow. | — |
| batch_processor.py | Core | Batch security evaluation engine — `evaluate_tool_batch`. Delegates interrupt payloads to `_batch_decisions` and review helpers to `_batch_review`. | ✅ |
| _batch_decisions.py | Internal | Interrupt payload construction and user approval decision application. | ✅ |
| _batch_review.py | Internal | LLM-based security review, runtime domain tracking, and skill hook evaluation. | ✅ |
| helpers.py | Core | Approval middleware helpers: dual-threshold denial tracking (consecutive + total) with proactive guidance and allowlist management. | ✅ |
| middleware.py | Core | Bridges the Permission Engine with the LangGraph tool pipeline. | ✅ |
| rate_limiter.py | Core | Approval rate limiter. Independent from core approval logic for easy testing and configuration. | ✅ |
| scheduler.py | Core | Approval timeout scheduler — auto-resumes agents when approval requests expire. Uses global decision format for batch-safe timeout resumption. | ✅ |

## Key Dependencies

- `observability`
