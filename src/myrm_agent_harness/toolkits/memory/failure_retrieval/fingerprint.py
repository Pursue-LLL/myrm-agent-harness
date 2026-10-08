# [POS]: myrm_agent_harness.toolkits.memory.failure_retrieval.fingerprint
# [INPUT]: models.py (ErrorFingerprint)
# [OUTPUT]: ErrorFingerprintExtractor

"""Error fingerprint extractor for failure-triggered session retrieval.

P0 delivery for Item 109 in topic_01 memory roadmap.
Scrubs dynamic UUIDs, memory addresses, timestamps, and ephemeral paths
to generate deterministic normalized error signatures suitable for indexing and lookup.

[INPUT]
- toolkits.memory.failure_retrieval.models::ErrorFingerprint (POS: Domain models for failure-triggered
  historical session retrieval.)

[OUTPUT]
- ErrorFingerprintExtractor: Normalizes runtime errors into deterministic error signatures.

[POS]
Error fingerprint extractor for failure-triggered session retrieval.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.failure_retrieval.models import (
    ErrorFingerprint,
)


class ErrorFingerprintExtractor:
    """Normalizes runtime errors into deterministic error signatures."""

    # Regex patterns for volatile tokens
    _UUID_PATTERN = re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    )
    _HEX_ADDR_PATTERN = re.compile(r"0x[0-9a-fA-F]{6,16}")
    _TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
    _TMP_PATH_PATTERN = re.compile(r"/(?:tmp|var/folders)/[a-zA-Z0-9_/.-]+")
    _PORT_PATTERN = re.compile(r":\d{4,5}\b")

    def extract(
        self,
        raw_error: str,
        error_type: str | None = None,
        tool_name: str | None = None,
        exit_code: int | None = None,
    ) -> ErrorFingerprint:
        """Extract a clean, scrubbed ErrorFingerprint from raw error text and context."""
        cleaned = raw_error.strip()

        # Scrub volatile components
        cleaned = self._UUID_PATTERN.sub("<UUID>", cleaned)
        cleaned = self._HEX_ADDR_PATTERN.sub("<ADDR>", cleaned)
        cleaned = self._TIMESTAMP_PATTERN.sub("<TIME>", cleaned)
        cleaned = self._TMP_PATH_PATTERN.sub("<TMP_PATH>", cleaned)

        # Detect error class if not explicitly provided
        detected_type = error_type or self._detect_error_type(cleaned)

        # Extract context tags
        tags = self._derive_context_tags(detected_type, cleaned, tool_name)

        return ErrorFingerprint(
            error_type=detected_type,
            tool_name=tool_name or "",
            normalized_pattern=cleaned[:300],
            exit_code=exit_code,
            context_tags=tags,
        )

    def _detect_error_type(self, text: str) -> str:
        """Infer canonical error class name from common exception traces."""
        # Check for explicit Python exception name at beginning or following colon
        match = re.search(r"\b([A-Z][a-zA-Z0-9_]*(?:Error|Exception|Timeout|Failure))\b", text)
        if match:
            return match.group(1)

        lower = text.lower()
        if "permission denied" in lower or "eacces" in lower:
            return "PermissionDeniedError"
        if "connection refused" in lower or "econnrefused" in lower:
            return "ConnectionRefusedError"
        if "address already in use" in lower or "eaddrinuse" in lower:
            return "PortAlreadyInUseError"
        if "rate limit" in lower or "too many requests" in lower or "429" in lower:
            return "RateLimitExceededError"
        if "not found" in lower or "no such file" in lower or "enoent" in lower:
            return "ResourceNotFoundError"

        return "GenericExecutionError"

    def _derive_context_tags(
        self, error_type: str, text: str, tool_name: str | None
    ) -> list[str]:
        """Categorize failure into domain tags."""
        tags: list[str] = []
        combined = f"{error_type} {text} {tool_name or ''}".lower()

        if any(w in combined for w in ["database", "sql", "postgres", "sqlite", "table", "migration"]):
            tags.append("database")
        if any(w in combined for w in ["git", "branch", "commit", "push", "remote"]):
            tags.append("git")
        if any(w in combined for w in ["connect", "socket", "timeout", "http", "network", "dns", "port"]):
            tags.append("network")
        if any(w in combined for w in ["auth", "token", "permission", "denied", "key", "401", "403"]):
            tags.append("security")
        if any(w in combined for w in ["docker", "container", "sandbox", "process", "kill"]):
            tags.append("infrastructure")

        return tags or ["general"]
