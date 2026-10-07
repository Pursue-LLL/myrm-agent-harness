# auto_recall/

## Overview
Targeted Experience Auto-Recall Trigger with Multi-Turn Dedup and Fail-Open Reranking Engine: 5 sensitive lifecycle triggers (task_start, skill_load, subagent_start, write_preflight, cron_start), 5-turn sliding window deduplication to prevent context fatigue, and SLA-bounded fail-open neural reranker fallback.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Targeted Experience Auto-Recall Trigger with Multi-Turn Dedup and Fail-Open Reranking. | ✅ |
| `fail_open_reranker.py` | Core | Fail-open reranker wrapper guaranteeing non-blocking fallback on missing keys or timeouts. | ✅ |
| `recall_gate.py` | Core | Facade orchestrator coordinating trigger classification, dedup, and fail-open reranking. | ✅ |
| `sliding_window_dedup.py` | Core | Sliding window deduplication gate to suppress redundant memory injection across turns. | ✅ |
| `trigger_classifier.py` | Core | Deterministic and lightweight classifier for 5 high-risk recall trigger scenarios. | ✅ |
| `types.py` | Types | Type definitions and contracts for Targeted Experience Auto-Recall Engine. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
