# approval/

## Overview
Tool approval subsystem — Human-in-the-Loop approval flow with correction learning.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Tool approval subsystem — Human-in-the-Loop approval flow. | — |
| batch_processor.py | Core | Batch security evaluation — `evaluate_tool_batch`. YOLO auto-approve (DENY always enforced). Fast-Path read-only MCP. **Pattern allowlist** auto-approve via `allowlist.check(..., command=shell_command)` when action is ASK. | ✅ |
| _batch_decisions.py | Internal | Interrupt payload and decision application (edit shell re-gate). | ✅ |
| _batch_review.py | Internal | LLM-based security review, runtime domain tracking, and skill hook evaluation. | ✅ |
| correction_learning.py | Core | HITL correction learning — converts approval edits/rejects into persistent SemanticMemory preferences and ProceduralMemory rules. Zero LLM cost (deterministic dict-diff classification). Fires on APPROVAL_CORRECTION hook. | ✅ |
| helpers.py | Core | Denial tracking, **allow-always four scopes** (permission/tool/exact/pattern via `derive_command_pattern`), allowlist persistence. | ✅ |
| middleware.py | Core | Bridges the Permission Engine with the LangGraph tool pipeline. Auto-denies approval for shadow agents (no UI channel). Fires APPROVAL_CORRECTION hook after decisions for correction learning. | ✅ |
| rate_limiter.py | Core | Approval rate limiter. Independent from core approval logic for easy testing and configuration. | ✅ |
| scheduler.py | Core | HITL timeout scheduler — auto-resumes agents when approval or Web clarification requests expire. Approval uses global decision format; clarification uses `resume_value_override` (empty dict → no_answer). Idempotent `resolve_if_first` prevents race conditions between timeout auto-resume and manual user resume. | ✅ |

## Key Dependencies

- `observability`
- `core.hooks` (APPROVAL_CORRECTION event)
- `toolkits.memory` (SemanticMemory, ProceduralMemory persistence)
