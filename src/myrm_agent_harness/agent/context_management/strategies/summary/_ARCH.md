# summary/

## Overview
LLM-based structured summarization strategy with quality gate, circuit breaker, and message reconstruction.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Re-exports public summary APIs. |
| `summarizer.py` | Core | LLM-invoked structured summarization with streaming progress tracking, cache-safe invocation, and aux-model context guard. |
| `summary_auditor.py` | Core | Quality gate that validates generated summaries for coverage and accuracy. |
| `summary_builder.py` | Core | Message history reconstruction after summarisation (protected head extraction, compacted messages assembly). |
| `summary_parser.py` | Core | Summary format parsing and message-to-text formatting with credential redaction. |
| `summary_prompts.py` | Core | Prompt templates for structured JSON summary and merge operations. |
| `summarize_circuit_guard.py` | Core | Circuit breaker shared by turn pipeline and server compact paths. |
| `progress_timeout.py` | Core | Progress-aware timeout primitives for detecting stalled summarization (InactivityTimeoutError, TotalCeilingTimeoutError). |

## Key Dependencies

- `...infra.schemas` (ContextConfig, StructuredSummary)
- `...tracking.artifact_tracker`
- `security.detection.leak_detector`
