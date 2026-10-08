"""Stream-safe secret scrubber for chunk-boundary holdback redaction.

[INPUT]
- Incremental text chunks emitted by LLMs, subprocess stdout/stderr, or streaming channels.

[OUTPUT]
- Scrubbed chunks with trailing partial secret prefixes held back until resolved.

[POS]
- Harness core security primitive in core/security/vault_secret_redaction/stream_scrubber.py.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

ANSI_ESCAPE_PATTERN = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi_codes(text: str) -> str:
    """Strip ANSI escape sequences from terminal or log output."""
    return ANSI_ESCAPE_PATTERN.sub("", text)


def compute_prefix_suffix_holdback_length(
    text: str, secret_values: Sequence[str], max_secret_len: int
) -> int:
    """Find the length of the longest suffix of text that is a prefix of any secret."""
    if not text or not secret_values or max_secret_len <= 0:
        return 0

    upper_bound = min(len(text), max_secret_len)
    for length in range(upper_bound, 0, -1):
        suffix = text[-length:]
        for secret in secret_values:
            if secret.startswith(suffix):
                return length
    return 0


class SecretStreamScrubber:
    """Sliding-window stream scrubber preventing secret leakage across chunk splits."""

    def __init__(
        self,
        secret_entries: Sequence[tuple[str, str]],
        mask_template: str = "{name}=<REDACTED>",
        strip_ansi: bool = True,
    ) -> None:
        self._mask_template = mask_template
        self._strip_ansi = strip_ansi
        # Filter and sort entries longest first to prevent prefix shadowing
        self._sorted_entries: list[tuple[str, str, str]] = []
        secret_vals: list[str] = []
        sorted_pairs = sorted(
            [pair for pair in secret_entries if pair[1]],
            key=lambda item: len(item[1]),
            reverse=True,
        )
        for name, val in sorted_pairs:
            mask = mask_template.format(name=name)
            self._sorted_entries.append((name, val, mask))
            secret_vals.append(val)

        self._secret_values: tuple[str, ...] = tuple(secret_vals)
        self._max_secret_length: int = (
            max((len(v) for v in self._secret_values), default=0)
        )
        self._tail: str = ""

    @property
    def held_back_length(self) -> int:
        """Current length of held-back characters in the buffer."""
        return len(self._tail)

    def _scrub_text(self, text: str) -> str:
        """Apply full string substitutions across sorted entries."""
        if not text:
            return ""
        processed = strip_ansi_codes(text) if self._strip_ansi else text
        for _, val, mask in self._sorted_entries:
            if val in processed:
                processed = processed.replace(val, mask)
        return processed

    def push(self, chunk: str) -> str:
        """Process an incremental chunk and emit safe redacted content."""
        if not chunk:
            return ""

        if self._max_secret_length == 0:
            return self._scrub_text(chunk)

        buffer = self._tail + chunk
        holdback_len = compute_prefix_suffix_holdback_length(
            buffer, self._secret_values, self._max_secret_length
        )

        if holdback_len > 0:
            emittable = buffer[:-holdback_len]
            self._tail = buffer[-holdback_len:]
        else:
            emittable = buffer
            self._tail = ""

        return self._scrub_text(emittable)

    def flush(self) -> str:
        """Flush any held-back trailing bytes at the end of the stream."""
        if not self._tail:
            return ""
        remaining = self._tail
        self._tail = ""
        return self._scrub_text(remaining)
