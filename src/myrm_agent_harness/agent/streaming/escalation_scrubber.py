"""Escalation marker scrubber — intercepts model self-upgrade markers in streaming output.

Detects markers like ``<<<NEEDS_PRO>>>`` or ``<<<NEEDS_PRO: reason>>>`` emitted by
DeepSeek-flash when the model judges that a stronger model is needed. Suppresses
the marker from reaching the user and sets a flag for the recovery layer to
trigger a model upgrade + retry.

[INPUT]
- (none) Pure state-machine with configurable marker pattern.

[OUTPUT]
- EscalationScrubber: stateful scrubber that buffers early chunks, detects escalation
  markers, and suppresses them from the stream pipeline.

[POS]
Streaming layer escalation detection. Sits before ReasoningScrubber in the
_dispatch_messages pipeline. When disabled (default for non-flash models),
it passes content through with zero overhead.
"""

from __future__ import annotations

import re

_DEFAULT_MARKER_PREFIX = "<<<NEEDS_PRO"
_DEFAULT_BUFFER_SIZE = 256

_MARKER_RE = re.compile(r"^<<<NEEDS_PRO(?::\s*([^>]*))?>>>")


class EscalationScrubber:
    """Detects model self-escalation markers at the start of a streaming response.

    Only inspects the *lead-in* of the response (first ``buffer_size`` characters).
    Mid-response occurrences are passed through as normal content so users
    discussing the marker text don't trigger false positives.

    Lifecycle:
    1. ``process(chunk)`` accumulates until the buffer is large enough to decide.
    2. If the marker matches → ``detected`` becomes True, all content is suppressed.
    3. If the buffer grows past the look-ahead window without a match →
       buffered content is flushed and future chunks pass through directly.
    4. ``flush()`` releases any remaining buffered content at stream end.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        marker_prefix: str = _DEFAULT_MARKER_PREFIX,
        buffer_size: int = _DEFAULT_BUFFER_SIZE,
    ) -> None:
        self._enabled = enabled
        self._marker_prefix = marker_prefix
        self._buffer_size = max(buffer_size, len(marker_prefix) + 16)

        self.detected = False
        self.reason: str | None = None

        self._buffer = ""
        self._decided = False

    def process(self, chunk: str) -> str | None:
        """Feed a streaming chunk. Returns text to forward downstream, or None to suppress."""
        if not self._enabled or self.detected:
            return None if self.detected else chunk

        if self._decided:
            return chunk

        self._buffer += chunk

        trimmed = self._buffer.lstrip()

        if len(trimmed) > 0 and not _could_be_partial_marker(trimmed, self._marker_prefix):
            self._decided = True
            result = self._buffer
            self._buffer = ""
            return result

        m = _MARKER_RE.match(trimmed)
        if m:
            self.detected = True
            reason = m.group(1)
            self.reason = reason.strip() if reason and reason.strip() else None
            self._buffer = ""
            return None

        if len(self._buffer) >= self._buffer_size:
            self._decided = True
            result = self._buffer
            self._buffer = ""
            return result

        return None

    def flush(self) -> str | None:
        """Flush remaining buffered content at stream end."""
        if not self._buffer:
            return None

        if self.detected:
            self._buffer = ""
            return None

        result = self._buffer
        self._buffer = ""
        return result

    def reset(self) -> None:
        """Reset state for a new turn (e.g. after escalation retry)."""
        self.detected = False
        self.reason = None
        self._buffer = ""
        self._decided = False


def _could_be_partial_marker(text: str, prefix: str) -> bool:
    """Check if text could be the beginning of an escalation marker.

    Returns True when text is a prefix of the marker pattern OR vice-versa,
    allowing the buffer to keep accumulating until a definitive decision.
    """
    check_len = min(len(text), len(prefix))
    if text[:check_len] != prefix[:check_len]:
        return False

    if len(text) <= len(prefix):
        return True

    rest = text[len(prefix):]
    return rest[0] in (">", ":")
