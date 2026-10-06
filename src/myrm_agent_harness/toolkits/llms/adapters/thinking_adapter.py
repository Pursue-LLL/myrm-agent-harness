"""Thinking model reasoning content unpacking and scrubbing adapter.

Handles Qwen3.5, DeepSeek-R1, and Ollama thinking models where responses place
reasoning traces in reasoning_content while leaving root content blank.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_THINK_TAG_REGEX = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_UNCLOSED_THINK_REGEX = re.compile(r"<think>[\s\S]*$", re.IGNORECASE)
_THOUGHT_PREFIX_REGEX = re.compile(r"^(?:thought|reasoning):\s*[\s\S]*?\n\n", re.IGNORECASE)
_CODE_BLOCK_REGEX = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


class ThinkingModelReasoningAdapter:
    """Adapts reasoning model responses, unpacks empty content, and scrubs CoT tokens."""

    @classmethod
    def scrub_thinking_tags(cls, text: str) -> str:
        """Strip <think>...</think> and unclosed reasoning blocks from text."""
        if not text:
            return ""

        cleaned = _THINK_TAG_REGEX.sub("", text)
        cleaned = _UNCLOSED_THINK_REGEX.sub("", cleaned)
        cleaned = _THOUGHT_PREFIX_REGEX.sub("", cleaned)
        return cleaned.strip()

    @classmethod
    def extract_effective_content(cls, payload: Mapping[str, object] | str) -> str:
        """Extract clean final content, falling back to reasoning_content if content is empty."""
        if isinstance(payload, str):
            return cls.scrub_thinking_tags(payload)

        # 1. Primary content inspection
        raw_content = payload.get("content")
        content_str = str(raw_content).strip() if raw_content is not None else ""
        scrubbed_content = cls.scrub_thinking_tags(content_str)
        if scrubbed_content:
            return scrubbed_content

        # 2. Fallback to reasoning_content or reasoning (Ollama / Qwen3.5 / DeepSeek-R1 behavior)
        raw_reasoning = payload.get("reasoning_content") or payload.get("reasoning")
        reasoning_str = str(raw_reasoning).strip() if raw_reasoning is not None else ""
        if not reasoning_str:
            return ""

        # 3. Check for enclosed code blocks inside reasoning text
        code_match = _CODE_BLOCK_REGEX.search(reasoning_str)
        if code_match:
            return code_match.group(1).strip()

        # 4. Check for embedded JSON payload (e.g. array or object)
        json_slice = cls.extract_json_block(reasoning_str)
        if json_slice:
            return json_slice

        # Fallback to scrubbed reasoning string itself
        return cls.scrub_thinking_tags(reasoning_str)

    @classmethod
    def extract_json_block(cls, text: str) -> str | None:
        """Extract first valid JSON array or object block from arbitrary mixed text."""
        if not text:
            return None

        # Look for array brackets [...]
        array_start = text.find("[")
        array_end = text.rfind("]")
        if array_start != -1 and array_end > array_start:
            return text[array_start : array_end + 1].strip()

        # Look for object braces {...}
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start != -1 and obj_end > obj_start:
            return text[obj_start : obj_end + 1].strip()

        return None
