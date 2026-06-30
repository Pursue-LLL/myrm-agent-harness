"""JSON log formatter with tracing fields.

Produces single-line JSON log records suitable for Loki, ELK, or
``jq``-based analysis. Enabled via ``MYRM_LOG_FORMAT=json`` environment
variable; otherwise the default text formatter is used.

Fields emitted::

    {
        "timestamp": "2026-06-30T23:00:00.123456",
        "level": "INFO",
        "logger": "myrm_agent_harness.core",
        "trace_id": "a1b2c3d4...",
        "session_id": "sess-xyz",
        "message": "Agent step completed"
    }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from myrm_agent_harness.core.security.redact import redact_sensitive_text


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON with automatic secret redaction.

    Expects ``trace_id`` and ``session_id`` to be injected by
    ``TracingLogFilter``; falls back to ``"-"`` if missing.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = redact_sensitive_text(record.getMessage())

        payload: dict[str, str | float] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "session_id": getattr(record, "session_id", "-"),
            "message": message,
        }

        if record.exc_info and not isinstance(record.exc_info, bool):
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)
