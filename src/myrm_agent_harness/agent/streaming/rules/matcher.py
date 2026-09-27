"""Streaming regex matcher and JSON unescaper for TTSR engine.

Maintains a bounded sliding window buffer (default 128 chars) across streaming chunks
to eliminate token boundary fragmentation while guaranteeing O(1) matching latency.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.agent.streaming.rules.types import (
    RuleTarget,
    StreamRule,
    TtsrMatchResult,
)


class PartialJsonUnescaper:
    """Stateful stream unescaper handling fragmented JSON escapes and Unicode code points."""

    def __init__(self) -> None:
        self._pending_escape: bool = False
        self._in_unicode: bool = False
        self._unicode_buffer: list[str] = []

    def unescape_chunk(self, chunk: str) -> str:
        """Streamingly unescape characters such as \\", \\\\, \\n, and \\uXXXX."""
        if not chunk:
            return ""

        result: list[str] = []
        for char in chunk:
            if self._in_unicode:
                if char in "0123456789abcdefABCDEF":
                    self._unicode_buffer.append(char)
                    if len(self._unicode_buffer) == 4:
                        hex_str = "".join(self._unicode_buffer)
                        try:
                            result.append(chr(int(hex_str, 16)))
                        except ValueError:
                            result.append(f"\\u{hex_str}")
                        self._in_unicode = False
                        self._unicode_buffer.clear()
                else:
                    hex_str = "".join(self._unicode_buffer)
                    result.append(f"\\u{hex_str}")
                    self._in_unicode = False
                    self._unicode_buffer.clear()
                    if char == "\\":
                        self._pending_escape = True
                    else:
                        result.append(char)
            elif self._pending_escape:
                self._pending_escape = False
                if char == "u":
                    self._in_unicode = True
                    self._unicode_buffer.clear()
                elif char == '"':
                    result.append('"')
                elif char == "\\":
                    result.append("\\")
                elif char == "/":
                    result.append("/")
                elif char == "n":
                    result.append("\n")
                elif char == "r":
                    result.append("\r")
                elif char == "t":
                    result.append("\t")
                else:
                    result.append(f"\\{char}")
            elif char == "\\":
                self._pending_escape = True
            else:
                result.append(char)
        return "".join(result)

    def reset(self) -> None:
        """Reset stateful escape tracking."""
        self._pending_escape = False
        self._in_unicode = False
        self._unicode_buffer.clear()


class TtsrMatcher:
    """Sliding-window regular expression matcher for active streaming channels."""

    def __init__(self, window_size: int = 128) -> None:
        self._window_size: int = max(32, window_size)
        self._buffers: dict[str, str] = {
            "assistant": "",
            "thinking": "",
            "tool_args": "",
        }
        self._unescaper: PartialJsonUnescaper = PartialJsonUnescaper()

    def feed_and_match(
        self,
        rules: Sequence[StreamRule],
        target: RuleTarget,
        chunk: str,
        turn: int,
    ) -> TtsrMatchResult | None:
        """Feed an incremental chunk into the target window and evaluate matching rules."""
        if not chunk or not rules:
            return None

        effective_target_key = "assistant" if target == "all" else target
        processed_chunk = chunk
        if effective_target_key == "tool_args":
            processed_chunk = self._unescaper.unescape_chunk(chunk)

        previous_buffer = self._buffers.get(effective_target_key, "")
        combined_text = previous_buffer + processed_chunk

        # Retain trailing window slice for continuous boundary matching
        self._buffers[effective_target_key] = combined_text[-self._window_size :]

        for rule in rules:
            if rule.target != "all" and rule.target != target:
                continue

            match = rule.pattern.search(combined_text)
            if match is not None:
                return TtsrMatchResult(
                    rule=rule,
                    matched_text=match.group(0),
                    target=target,
                    turn=turn,
                )

        return None

    def reset(self) -> None:
        """Clear all sliding window buffers and unescaper state."""
        for key in self._buffers:
            self._buffers[key] = ""
        self._unescaper.reset()
