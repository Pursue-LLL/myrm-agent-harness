# segment_guard/

## Overview
Bounded segment execution primitives used by the host's job supervisor. A long-running
job runs as bounded segments so a crash resumes from a checkpoint instead of repeating
side effects; these two guards make that contract safe.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports the appender, the budget and their error types. | — |
| `appender.py` | Core | `AtomicSegmentAppender.append_with_tail_check` normalizes newlines, verifies the file really ends with the tail the caller expects (O(1) reverse read, no whole-file scan) and only then appends with `flush` + `fsync`; a mismatch raises `TailMismatchError` instead of corrupting a file another writer truncated. | ✅ |
| `budget.py` | Core | `BoundedSegmentBudget` counts a segment's steps and raises `StepBudgetExceededError` when the budget is spent, so the segment yields and settles its checkpoint rather than running unbounded. | ✅ |

## Architecture Alignment
- Pure runtime primitives: no dependency on `agent/`, `toolkits/` or the host server.
- No I/O beyond the file the caller names, so it is safe inside a supervisor critical section.
