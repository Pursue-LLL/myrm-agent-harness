"""Stream repetition scrubber — intercepts degenerate LLM repetition loops during streaming.

[INPUT]
- Pure streaming text fragments.

[OUTPUT]
- StreamRepetitionScrubber: stateful detector tracking rolling character windows.
  Detects verbatim repetition loops in real-time, respects code block syntax
  to avoid false positives, and signals cancellation via CancellationToken.

[POS]
Streaming layer content-sanity scrubber. Sits in the _dispatch_messages pipeline.
Prevents runaway token consumption and UI flooding from degenerated LLM generation.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

# Minimum accumulated text length before triggering repetition inspection
_MIN_TEXT_LENGTH = 300

# Base sliding window length (characters)
_BASE_REPEAT_WINDOW = 60

# Base minimum repeat count required to trip the detector
_BASE_MIN_REPEAT_COUNT = 4

# Minimum fraction of total text covered by the repeated window
_BASE_DOMINANCE_RATIO = 0.45


class StreamRepetitionScrubber:
    """Stateful scrubber to detect runaway verbatim repetition loops in streaming content.

    Features:
    1. O(N) sliding character window with fast line-level heuristics.
    2. Grammar/context-aware threshold scaling: inside Markdown code blocks (```),
       thresholds are relaxed to prevent false positives on repetitive data/code.
    3. Seamless integration with CancellationToken to abort stream immediately.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        self.enabled = enabled
        self._cancel_token = cancel_token
        self.detected = False
        self.aborted_reason: str | None = None
        self._accumulated_text = ""
        self._in_code_block = False

    def process(self, chunk: str) -> str | None:
        """Process incoming text chunk.

        Returns:
            The text chunk if normal; None if stream was aborted due to repetition.
        """
        if not self.enabled or self.detected:
            return chunk if not self.detected else None

        self._accumulated_text += chunk
        self._update_code_block_state()

        n = len(self._accumulated_text)
        if n < _MIN_TEXT_LENGTH:
            return chunk

        if self._check_repetition(n):
            self.detected = True
            self.aborted_reason = (
                f"Model repetition loop detected ({n} chars processed). "
                "Stream aborted to prevent token waste and flooding."
            )
            if self._cancel_token is not None:
                self._cancel_token.cancel()
            return None

        return chunk

    def _update_code_block_state(self) -> None:
        """Track triple-backtick toggles globally across all accumulated text."""
        self._in_code_block = (self._accumulated_text.count("```") % 2 == 1)

    def _check_repetition(self, n: int) -> bool:
        """Check if accumulated text is dominated by verbatim repetition."""
        text = self._accumulated_text

        # Scale thresholds if inside code block to prevent false positives on data tables
        min_repeats = _BASE_MIN_REPEAT_COUNT * 2 if self._in_code_block else _BASE_MIN_REPEAT_COUNT
        dominance_ratio = 0.70 if self._in_code_block else _BASE_DOMINANCE_RATIO
        window = _BASE_REPEAT_WINDOW * 2 if self._in_code_block else _BASE_REPEAT_WINDOW

        # 1. Fast path: line-level repetition check
        if self._check_line_repetition(text, n, min_repeats, dominance_ratio):
            return True

        # 2. General path: sliding character window
        if n < window * min_repeats:
            return False

        needed = max(min_repeats, math.ceil(n * dominance_ratio / window))
        counts: dict[str, int] = {}
        step = max(1, window // 8)  # Step optimization for O(N/k) performance

        for i in range(0, n - window + 1, step):
            key = text[i : i + window]
            c = counts.get(key, 0) + 1
            if c >= needed:
                return True
            counts[key] = c

        return False

    @staticmethod
    def _check_line_repetition(
        text: str,
        total_len: int,
        min_repeats: int,
        dominance_ratio: float,
    ) -> bool:
        """Fast path check for repeated normalized lines."""
        lines = text.splitlines()
        if len(lines) < min_repeats:
            return False

        counts: dict[str, int] = {}
        for line in lines:
            norm = line.strip()
            # Ignore trivially short lines (empty, single brackets/punctuation)
            if len(norm) < 8:
                continue
            counts[norm] = counts.get(norm, 0) + 1

        for line, count in counts.items():
            if count >= min_repeats and (count * len(line)) >= (total_len * dominance_ratio):
                return True

        return False
