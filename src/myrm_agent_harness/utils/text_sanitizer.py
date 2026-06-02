"""LLM 流式输出文本清洗

[INPUT]
- re::re (POS: Python 正则表达式库)
- agent.streaming.reasoning_scrubber::THINKING_TAG_NAMES (POS: canonical thinking tag name set)

[OUTPUT]
- sanitize_llm_output(): 移除 LLM 推理标签、控制 token 和无效 Unicode
- extract_and_strip_think_blocks(): 静态提取 reasoning 内容并剥离原文本标签，用于历史记录提纯

[POS]
LLM streaming output sanitizer. Three-layer filtering ensures clean, garble-free text for user display.

"""

from __future__ import annotations

import re
from functools import lru_cache

from myrm_agent_harness.core.events import THINKING_TAG_NAMES

_REASONING_TAG_NAMES = "|".join(THINKING_TAG_NAMES)


@lru_cache(maxsize=1)
def _think_block_re() -> re.Pattern[str]:
    """Matches paired reasoning tags and their content (non-greedy). Group 1 captures the inner reasoning text."""
    return re.compile(
        rf"<(?:{_REASONING_TAG_NAMES})(?:\s[^>]*)?>(.*?)</(?:{_REASONING_TAG_NAMES})>",
        re.DOTALL | re.IGNORECASE,
    )


@lru_cache(maxsize=1)
def _think_orphan_re() -> re.Pattern[str]:
    """Matches orphaned (unpaired) reasoning open/close tags."""
    return re.compile(
        rf"</?(?:{_REASONING_TAG_NAMES})\b[^>]*>",
        re.IGNORECASE,
    )


@lru_cache(maxsize=1)
def _compiled_sanitizer() -> re.Pattern[str]:
    """Compiled regex for control-character and model-token removal."""
    patterns = [
        r"[\x00-\x08\x0B\x0C\x0E-\x1F]",
        r"[\x7F-\x9F]",
        r"<\|[a-zA-Z_]\w*\|>",
        r"\uFFFD",
        r"[\uD800-\uDFFF]",
    ]
    return re.compile("|".join(patterns))


def extract_and_strip_think_blocks(text: str) -> tuple[str, str]:
    """Extract reasoning blocks from text and strip them from the original.

    This handles extracting ``<think>...</think>`` (and variants) into a combined
    reasoning string, while returning the remaining clean content.
    Control characters are also stripped.

    Args:
        text: Raw text to parse.

    Returns:
        A tuple of (clean_content, reasoning_content).
    """
    if not text:
        return "", ""

    reasoning_parts = []
    if "<" in text:
        # Find and extract all thinking blocks
        for match in _think_block_re().finditer(text):
            reasoning_parts.append(match.group(1).strip())

        # Strip the tags from the text
        text = _think_block_re().sub("", text)
        text = _think_orphan_re().sub("", text)

    clean_text = _compiled_sanitizer().sub("", text).strip()
    reasoning_text = _compiled_sanitizer().sub("", "\n\n".join(reasoning_parts)).strip()

    return clean_text, reasoning_text


def sanitize_text(text: str) -> str:
    """Remove reasoning tags, control tokens and invalid Unicode from text.

    Generic text sanitizer that can be used for any text source (LLM output,
    user input, database content, etc.). Performs three-layer filtering:

    1. **Paired reasoning blocks** — ``<think>…</think>`` and variants
       (thinking, thought, antthinking, reasoning, REASONING_SCRATCHPAD)
       with their enclosed content.
    2. **Orphaned reasoning tags** — stray open/close tags left after
       step 1 (e.g. ``</think>`` without a matching ``<think>``).
    3. **Control characters** — C0/C1 control chars, model-specific
       tokens ``<|…|>``, replacement char ``\\uFFFD``, unpaired surrogates.

    A fast-path check skips the reasoning-tag regex when no ``<`` is
    present in *text* (the common case for most text).

    Args:
        text: Raw text to sanitize.

    Returns:
        Sanitized text (may be empty string).
    """
    if not text:
        return text
    if "<" in text:
        text = _think_block_re().sub("", text)
        text = _think_orphan_re().sub("", text)
    return _compiled_sanitizer().sub("", text)


def sanitize_llm_output(text: str) -> str:
    """Remove reasoning tags, control tokens and invalid Unicode from LLM output.

    Specialized alias for ``sanitize_text`` with semantic naming for
    LLM output context. Performs the same sanitization as ``sanitize_text``.

    This function is called automatically by the event pipeline on every
    streaming MESSAGE chunk before it reaches the user.

    Args:
        text: Raw text chunk from the LLM.

    Returns:
        Sanitized text (may be empty string).
    """
    return sanitize_text(text)
