"""Hook output spiller: prevent oversized hook outputs from bloating context.

When a hook (especially LLM or command hooks) produces a large additional_context,
it gets written to disk and replaced with a truncated preview + file path reference.

This prevents hooks from accidentally blowing up the context window.

Threshold: 2500 tokens (matches codex-cli's HOOK_OUTPUT_TOKEN_LIMIT).
Storage: <PERSISTENT_ROOT>/.hook_outputs/<session_id>/<uuid>.txt

[INPUT]
- utils.text_utils::get_token_count (POS: Token counting)
- runtime.execution_paths::PERSISTENT_ROOT (POS: Storage root)

[OUTPUT]
- HookOutputSpiller: spill oversized hook text to disk
- spill_hook_contexts: convenience function for batch spilling

[POS]
Defensive guard preventing hook-produced context from bloating the conversation window.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from myrm_agent_harness.runtime.execution_paths import PERSISTENT_ROOT
from myrm_agent_harness.utils.text_utils import get_token_count

logger = logging.getLogger(__name__)

HOOK_OUTPUT_TOKEN_LIMIT = 2500
_HOOK_OUTPUTS_DIR = ".hook_outputs"


class HookOutputSpiller:
    """Spill oversized hook outputs to disk, returning truncated preview + path."""

    __slots__ = ("_output_dir",)

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self._output_dir = Path(output_dir) if output_dir else Path(PERSISTENT_ROOT) / _HOOK_OUTPUTS_DIR

    async def maybe_spill_text(self, text: str, session_id: str = "") -> str:
        """Check token count; if over limit, write full text to disk and return preview.

        Args:
            text: Hook output text to check
            session_id: Session identifier for file organization

        Returns:
            Original text if under limit, otherwise truncated preview + file path
        """
        if not text:
            return text

        token_count = get_token_count(text)
        if token_count <= HOOK_OUTPUT_TOKEN_LIMIT:
            return text

        file_path = self._build_path(session_id)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(text, encoding="utf-8")
            logger.info(
                "Hook output spilled to disk: %d tokens → %s",
                token_count,
                file_path,
            )
        except OSError as exc:
            logger.warning("Failed to write hook output to %s: %s", file_path, exc)
            return _truncate_preview(text)

        return _build_preview(text, file_path)

    async def maybe_spill_texts(self, texts: list[str], session_id: str = "") -> list[str]:
        """Batch spill: process each text independently."""
        return [await self.maybe_spill_text(t, session_id) for t in texts]

    def _build_path(self, session_id: str) -> Path:
        subdir = session_id or "anonymous"
        return self._output_dir / subdir / f"{uuid.uuid4().hex}.txt"


def _truncate_preview(text: str) -> str:
    """Truncate text to fit within token limit (fallback when disk write fails)."""
    # Simple char-based approximation: 1 token ≈ 4 chars
    max_chars = HOOK_OUTPUT_TOKEN_LIMIT * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def _build_preview(text: str, file_path: Path) -> str:
    """Build model-visible replacement with head/tail preview + recovery path."""
    footer = f"\n\nFull hook output saved to: {file_path}"
    # Budget: reserve tokens for footer
    footer_tokens = get_token_count(footer)
    preview_budget = max(200, HOOK_OUTPUT_TOKEN_LIMIT - footer_tokens)

    # Split text: 70% head, 30% tail
    head_chars = int(preview_budget * 4 * 0.7)
    tail_chars = int(preview_budget * 4 * 0.3)

    if len(text) <= head_chars + tail_chars + 50:
        return text + footer

    head = text[:head_chars]
    tail = text[-tail_chars:] if tail_chars > 0 else ""
    return f"{head}\n...[{len(text) - head_chars - tail_chars} chars omitted]...\n{tail}{footer}"


async def spill_hook_contexts(
    contexts: list[str],
    session_id: str = "",
    spiller: HookOutputSpiller | None = None,
) -> list[str]:
    """Convenience: spill a list of hook additional_contexts.

    Args:
        contexts: List of additional_context strings from hooks
        session_id: Session identifier
        spiller: Optional spiller instance (creates default if None)

    Returns:
        List of (possibly spilled) context strings
    """
    if not contexts:
        return contexts
    s = spiller or HookOutputSpiller()
    return await s.maybe_spill_texts(contexts, session_id)
