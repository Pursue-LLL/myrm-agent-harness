# [INPUT]: ConversationArchiveShareConfig, SanitizedShareMessage, ShareAccessPolicy, ShareableSnapshotManifest
# [OUTPUT]: SanitizedSnapshotExporter
# [POS]: agent/context_management/conversation_archive_share/sanitized_snapshot_exporter.py

"""Sanitized conversation snapshot exporter redacting credentials and computing signatures.

[INPUT]
- ConversationArchiveShareConfig, SanitizedShareMessage, ShareAccessPolicy, ShareableSnapshotManifest.

[OUTPUT]
- SanitizedSnapshotExporter: Strips internal metadata and sensitive keys to produce signed shareable snapshots.

[POS]
Data sanitization and cryptographic signing layer for shareable conversation snapshots.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
import uuid
from typing import Mapping, Sequence

from .archive_share_types import (
    ConversationArchiveShareConfig,
    SanitizedShareMessage,
    ShareAccessPolicy,
    ShareableSnapshotManifest,
)


class SanitizedSnapshotExporter:
    """Exports conversation turns into sanitized, HMAC-signed immutable shareable snapshots."""

    def __init__(self, config: ConversationArchiveShareConfig | None = None) -> None:
        self._config = config or ConversationArchiveShareConfig()
        self._compiled_patterns = [
            re.compile(pat) for pat in self._config.sensitive_patterns
        ]

    def export_snapshot(
        self,
        session_id: str,
        title: str,
        raw_messages: Sequence[Mapping[str, str | float | Sequence[str]]],
        ttl_seconds: float | None = None,
        policy: ShareAccessPolicy = ShareAccessPolicy.PUBLIC_READONLY,
        timestamp: float | None = None,
        share_id: str | None = None,
    ) -> ShareableSnapshotManifest:
        """Transforms raw conversation messages into a sanitized, signed shareable manifest."""
        now = timestamp if timestamp is not None else time.time()
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._config.default_share_ttl_seconds
        expires_at = (now + effective_ttl) if effective_ttl > 0 else None
        sid = share_id or f"share_{uuid.uuid4().hex[:16]}"

        sanitized_messages: list[SanitizedShareMessage] = []
        total_redactions = 0

        # Truncate to max allowed messages if exceeded
        target_messages = raw_messages[:self._config.max_snapshot_messages]

        for msg in target_messages:
            role = str(msg.get("role", "user"))
            raw_content = str(msg.get("content", ""))
            ts = float(msg.get("timestamp", now))

            # Sanitize content
            clean_content, count = self._redact_secrets(raw_content)
            total_redactions += count

            # Sanitize tool calls
            raw_tools = msg.get("sanitized_tool_calls") or msg.get("tool_calls") or ()
            clean_tools: list[str] = []
            if isinstance(raw_tools, (list, tuple)):
                for tool_item in raw_tools:
                    clean_tool, c = self._redact_secrets(str(tool_item))
                    clean_tools.append(clean_tool)
                    total_redactions += c

            sanitized_messages.append(
                SanitizedShareMessage(
                    role=role,
                    content=clean_content,
                    timestamp=ts,
                    sanitized_tool_calls=tuple(clean_tools),
                )
            )

        messages_tuple = tuple(sanitized_messages)
        signature = self.compute_signature(
            share_id=sid,
            session_id=session_id,
            title=title,
            messages=messages_tuple,
            expires_at=expires_at,
        )

        return ShareableSnapshotManifest(
            share_id=sid,
            session_id=session_id,
            title=title,
            messages=messages_tuple,
            signature=signature,
            created_at=now,
            expires_at=expires_at,
            redactions_count=total_redactions,
            policy=policy,
        )

    def compute_signature(
        self,
        share_id: str,
        session_id: str,
        title: str,
        messages: Sequence[SanitizedShareMessage],
        expires_at: float | None,
    ) -> str:
        """Computes HMAC-SHA256 signature for tamper-evident manifest verification."""
        content_parts = [
            share_id,
            session_id,
            title,
            str(expires_at or "never"),
        ]
        for m in messages:
            content_parts.append(f"{m.role}:{m.content}:{','.join(m.sanitized_tool_calls)}")

        canonical_data = "\n".join(content_parts).encode("utf-8")
        secret_bytes = self._config.signing_secret.encode("utf-8")
        return hmac.new(secret_bytes, canonical_data, hashlib.sha256).hexdigest()

    def _redact_secrets(self, text: str) -> tuple[str, int]:
        """Replaces detected sensitive keys and tokens with standard placeholder."""
        count = 0
        cleaned = text
        for pattern in self._compiled_patterns:
            matches = list(pattern.finditer(cleaned))
            if matches:
                count += len(matches)
                cleaned = pattern.sub("[REDACTED_SECRET]", cleaned)
        return cleaned, count
