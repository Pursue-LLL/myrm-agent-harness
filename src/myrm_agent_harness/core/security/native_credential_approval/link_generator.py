"""Precise message sequence link generator and parser for conversation transcripts.

[INPUT]
- Session ID, message ID, sequence number, and URL query strings.

[OUTPUT]
- Standardized PreciseMessageLink deep links and parsed MessageSequenceRef coordinates.

[POS]
- Core link resolution utility mirroring QM #1502 message-link mechanics.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse

from .types import MessageSequenceRef, PreciseMessageLink

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-\.:]+$")


class MessageLinkGenerator:
    """Generates and validates safe, unambiguous transcript deep links."""

    def __init__(self, base_route_prefix: str = "/chat") -> None:
        self._prefix = base_route_prefix.rstrip("/")

    def generate_link(
        self,
        session_id: str,
        message_id: str,
        sequence_number: int,
    ) -> PreciseMessageLink:
        """Construct a standardized deep link to an exact message in the conversation transcript."""
        if not session_id or not _SAFE_ID_RE.match(session_id):
            raise ValueError(f"Invalid or unsafe session_id format: '{session_id}'")
        if not message_id or not _SAFE_ID_RE.match(message_id):
            raise ValueError(f"Invalid or unsafe message_id format: '{message_id}'")
        if sequence_number < 0:
            raise ValueError(f"sequence_number must be non-negative, got: {sequence_number}")

        path = f"{self._prefix}/{session_id}"
        query = urlencode({"seq": sequence_number, "msg": message_id})
        deep_link_url = f"{path}?{query}"

        return PreciseMessageLink(
            path=path,
            sequence_number=sequence_number,
            message_id=message_id,
            deep_link_url=deep_link_url,
        )

    def parse_link(self, deep_link_url: str) -> MessageSequenceRef | None:
        """Parse and validate message sequence coordinates from a deep link URL."""
        if not deep_link_url:
            return None

        parsed = urlparse(deep_link_url)
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2 or f"/{path_parts[0]}" != self._prefix:
            return None

        session_id = path_parts[1]
        params = parse_qs(parsed.query)
        seq_values = params.get("seq")
        msg_values = params.get("msg")

        if not seq_values or not msg_values:
            return None

        try:
            seq_num = int(seq_values[0])
            if seq_num < 0:
                return None
        except ValueError:
            return None

        message_id = msg_values[0]
        if not _SAFE_ID_RE.match(session_id) or not _SAFE_ID_RE.match(message_id):
            return None

        return MessageSequenceRef(
            session_id=session_id,
            message_id=message_id,
            sequence_number=seq_num,
        )
