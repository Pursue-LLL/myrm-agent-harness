"""Security guard for external asset migration.

[POS]
Defends against denial-of-service file bombs, oversized memory uploads,
and prompt injection directives hidden within imported documents.

[INPUT]
- pathlib.Path, re
- .models.MigrationSecurityPolicy

[OUTPUT]
- MigrationSecurityGuard, SecurityLimitExceededError
"""

from __future__ import annotations

import re
from pathlib import Path

from myrm_agent_harness.toolkits.memory.migration.models import MigrationSecurityPolicy


class SecurityLimitExceededError(ValueError):
    """Raised when an uploaded file or batch exceeds safe size limits."""


# Common patterns attempting prompt injection or system override
_INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore\s+(all\s+)?(previous|prior)\s+instructions\b"),
    re.compile(r"(?i)\bdisregard\s+(all\s+)?(previous|prior)\s+commands\b"),
    re.compile(r"(?i)\bsystem\s+prompt\s+override\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+in\s+developer\s+mode\b"),
    re.compile(r"(?i)\bbypass\s+(all\s+)?safety\s+guardrails\b"),
]


class MigrationSecurityGuard:
    """Enforces size limits and cleanses hostile injection patterns from external memories."""

    def __init__(self, policy: MigrationSecurityPolicy | None = None) -> None:
        self._policy = policy or MigrationSecurityPolicy()

    @property
    def policy(self) -> MigrationSecurityPolicy:
        return self._policy

    def validate_file(self, file_path: Path | str) -> int:
        """Validate single file size against security policy limit.

        Returns file size in bytes if valid.
        Raises SecurityLimitExceededError if limit is breached.
        """
        path = Path(file_path)
        if not path.is_file():
            return 0
        size = path.stat().st_size
        if size > self._policy.max_file_size_bytes:
            msg = (
                f"File '{path.name}' size ({size} bytes) exceeds safety cap "
                f"({self._policy.max_file_size_bytes} bytes)"
            )
            raise SecurityLimitExceededError(msg)
        return size

    def validate_batch(self, total_bytes: int) -> None:
        """Validate cumulative batch size against total memory payload cap."""
        if total_bytes > self._policy.max_batch_bytes:
            msg = (
                f"Batch migration payload ({total_bytes} bytes) exceeds total limit "
                f"({self._policy.max_batch_bytes} bytes)"
            )
            raise SecurityLimitExceededError(msg)

    def sanitize_text(self, text: str) -> str:
        """Filter dangerous prompt injection commands and truncate oversized items."""
        if not text:
            return ""

        cleansed = text
        if self._policy.sanitize_prompt_injection:
            for pattern in _INJECTION_PATTERNS:
                cleansed = pattern.sub("[REDACTED_INJECTION_DIRECTIVE]", cleansed)

        # Enforce character cap
        if len(cleansed) > self._policy.max_content_chars_per_item:
            cleansed = cleansed[: self._policy.max_content_chars_per_item] + "... [TRUNCATED]"

        return cleansed.strip()
