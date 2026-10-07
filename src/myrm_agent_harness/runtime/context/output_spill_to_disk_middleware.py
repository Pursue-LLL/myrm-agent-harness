"""Output spill to disk middleware.

Caps terminal command outputs at a deterministic threshold (default 30k chars),
writes oversized outputs to durable disk storage, and returns an informative
head-tail diagnostic summary, preventing single commands from exhausting the context window.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .quiet_command_spill_types import OutputSpillReceipt


class OutputSpillToDiskMiddleware:
    """Middleware that intercepts command outputs and offloads oversized payloads to disk."""

    def __init__(
        self,
        max_output_chars: int = 30000,
        spill_directory: Path | str = "/tmp/myrm_spill",
        head_preview_chars: int = 500,
        tail_preview_chars: int = 1000,
        chars_per_token_ratio: float = 3.8,
    ) -> None:
        self._max_chars = max_output_chars
        self._spill_dir = Path(spill_directory)
        self._head_chars = head_preview_chars
        self._tail_chars = tail_preview_chars
        self._chars_per_token_ratio = chars_per_token_ratio

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count deterministically."""
        if not text.strip():
            return 0
        return max(1, math.ceil(len(text) / self._chars_per_token_ratio))

    def process_output(
        self,
        output_text: str,
        exit_code: int = 0,
        command: str = "",
    ) -> OutputSpillReceipt:
        """Evaluates output size and offloads to disk if threshold is exceeded."""
        orig_len = len(output_text)
        sha256 = hashlib.sha256(output_text.encode("utf-8")).hexdigest()

        if orig_len <= self._max_chars:
            return OutputSpillReceipt(
                is_spilled=False,
                exit_code=exit_code,
                original_char_count=orig_len,
                spilled_file_path=None,
                context_snippet=output_text,
                saved_tokens=0,
                checksum_sha256=sha256,
                metadata={"command": command},
            )

        # Ensure directory exists and write payload to disk
        self._spill_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"myrm_cmd_spill_{sha256[:12]}.log"
        spill_file = self._spill_dir / file_name
        spill_file.write_text(output_text, encoding="utf-8")

        # Construct Head-Tail context diagnostic snippet
        head = output_text[: self._head_chars].strip()
        tail = output_text[-self._tail_chars :].strip()
        truncated_count = orig_len - (len(head) + len(tail))

        snippet = (
            f"[Command Output Exceeded Safe Limit: {orig_len:,} chars (limit {self._max_chars:,}) | "
            f"exit_code={exit_code} | Written to {spill_file.resolve()}]\n"
            f"--- [Head Output ({len(head)} chars)] ---\n{head}\n"
            f"... [TRUNCATED {truncated_count:,} CHARS - Inspect full log at {spill_file.resolve()}] ...\n"
            f"--- [Tail Diagnostics ({len(tail)} chars)] ---\n{tail}"
        )

        orig_tokens = self.estimate_tokens(output_text)
        snippet_tokens = self.estimate_tokens(snippet)
        saved = max(0, orig_tokens - snippet_tokens)

        return OutputSpillReceipt(
            is_spilled=True,
            exit_code=exit_code,
            original_char_count=orig_len,
            spilled_file_path=str(spill_file.resolve()),
            context_snippet=snippet,
            saved_tokens=saved,
            checksum_sha256=sha256,
            metadata={
                "command": command,
                "spilled_file": str(spill_file.resolve()),
                "truncated_chars": str(truncated_count),
            },
        )
