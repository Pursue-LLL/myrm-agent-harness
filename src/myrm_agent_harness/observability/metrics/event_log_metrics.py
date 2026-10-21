"""Event log persistence metrics (JSONL backend, etc.).

[INPUT]

[OUTPUT]
- Counters for oversized JSONL lines and other event-log I/O edge cases

[POS]
Framework-level metrics; myrm-agent-server / UIs can scrape the same myrm_ series.
"""

from __future__ import annotations

from myrm_agent_harness.observability.metrics import create_counter

# JSONL: serialized line exceeded max bytes; line replaced with summary (see file_backend)
event_log_jsonl_line_downgraded_total = create_counter(
    "event_log_jsonl_line_downgraded_total",
    "Event log JSONL line exceeded configured max UTF-8 bytes; payload replaced with a minimal summary",
    (),
)

__all__ = [
    "event_log_jsonl_line_downgraded_total",
]
