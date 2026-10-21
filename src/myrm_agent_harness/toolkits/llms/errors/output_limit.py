"""Output-token limits that a provider states when it rejects a request.

[INPUT]
- errors.classifier::normalize_provider_error (POS: lower-cased text of an error including nested bodies)

[OUTPUT]
- OutputLimit: the largest ``max_tokens`` a provider says it accepts, and what kind of statement that is
- parse_output_limit(): read an OutputLimit from a rejected-request exception

[POS]
Pure wording parser shared by the generation retry loops and the presumed-overflow gate. It only
reads numbers the provider printed itself; every other rejection yields None, so callers keep their
existing failure behaviour for anything this module does not recognise.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from myrm_agent_harness.toolkits.llms.errors.classifier import normalize_provider_error

_NUM = r"(\d[\d,]*)"


@dataclass(frozen=True, slots=True)
class OutputLimit:
    """A provider-stated limit on the completion budget of a rejected request.

    ``model_cap`` is True when the provider named the model's own output ceiling, which holds for
    every request to that model. It is False when the number is what this single request's context
    window has left after its prompt, which changes as the prompt does.
    """

    tokens: int
    model_cap: bool


# Wordings in which the provider names the model's own output ceiling.
_MODEL_CEILING_PATTERNS: tuple[re.Pattern[str], ...] = (
    # DashScope: "Range of max_tokens should be [1, 8192]"
    re.compile(rf"range of max_tokens should be\s*\[\s*\d+\s*,\s*{_NUM}\s*\]"),
    # DeepSeek: "the valid range of max_tokens is [1, 8192]"
    re.compile(rf"valid range of max_tokens is\s*\[\s*\d+\s*,\s*{_NUM}\s*\]"),
    # Azure / OpenAI: "This model supports at most 16384 completion tokens"
    re.compile(rf"supports at most\s+{_NUM}\s+completion tokens"),
    # Anthropic: "max_tokens: 8192 > 4096, which is the maximum allowed number of output tokens for <model>"
    re.compile(rf"max_tokens:\s*\d+\s*>\s*{_NUM}\s*,\s*which is the maximum allowed number of output tokens"),
    # OpenAI-compatible gateways: "max_tokens (384000) exceeds model's maximum output tokens (65536)"
    re.compile(
        rf"max_\w*tokens\s*\(\s*\d+\s*\)\s*exceeds (?:the )?(?:model's )?maximum output tokens\s*\(\s*{_NUM}\s*\)"
    ),
    # Volcengine Ark: "The parameter `max_tokens` ... is not valid: integer above maximum value, expected a value <= N"
    re.compile(rf"max_(?:completion_)?tokens\W.{{0,120}}?integer above maximum value\W+expected a value\s*<=\s*{_NUM}"),
    # Groq: "max_completion_tokens must be less than or equal to 40960"
    re.compile(rf"max_(?:completion_)?tokens must be less than or equal to\s*{_NUM}"),
)

# Wordings in which the provider prints the room its context window leaves for the completion.
_AVAILABLE_TOKENS_RE = re.compile(r"available\s*_?tokens\s*:\s*(\d+)")
_OPENROUTER_BREAKDOWN_RE = re.compile(r"\((\d+)\s+of text input,\s*(\d+)\s+of tool input,\s*\d+\s+in the output\)")
_MAX_CTX_LENGTH_RE = re.compile(r"maximum context length is (\d+)\s*token")
_CHAR_PROMPT_RE = re.compile(r"prompt contains (\d+)\s*character")
_INPUT_TOKENS_RE = re.compile(r"prompt contains (?:at least )?(\d+)\s*input tokens")
_OPENAI_SPLIT_RE = re.compile(rf"\(\s*{_NUM}\s+in (?:the messages|your prompt)")
_PASSED_INPUT_TOKENS_RE = re.compile(
    rf"you passed\s+{_NUM}\s+input tokens.*?context length is only\s+{_NUM}\s+tokens", re.S
)
_CONTEXT_SUM_RE = re.compile(rf"exceed context limit\D*{_NUM}\s*\+\s*{_NUM}\s*>\s*{_NUM}")

# Keyword groups that mark a message as an output-budget complaint for the window formats whose
# regexes alone are loose (they also appear in plain prompt-overflow rejections).
_OUTPUT_BUDGET_KEYWORDS: tuple[tuple[str, ...], ...] = (
    ("max_tokens", "available_tokens"),
    ("max_tokens", "available tokens"),
    ("in the output", "maximum context length"),
    ("maximum context length", "requested", "output tokens"),
)


def _as_int(raw: str) -> int:
    return int(raw.replace(",", ""))


def _looks_like_output_budget_error(msg: str) -> bool:
    return any(all(keyword in msg for keyword in group) for group in _OUTPUT_BUDGET_KEYWORDS)


def _model_ceiling(msg: str) -> int | None:
    for pattern in _MODEL_CEILING_PATTERNS:
        match = pattern.search(msg)
        if match and (tokens := _as_int(match.group(1))) >= 1:
            return tokens
    return None


def _remainder_candidates(msg: str) -> Iterator[int]:
    """Yield the completion room each recognised wording implies, most direct statement first."""
    gated = _looks_like_output_budget_error(msg)
    ctx = _MAX_CTX_LENGTH_RE.search(msg)
    window = int(ctx.group(1)) if ctx else 0

    if gated and (match := _AVAILABLE_TOKENS_RE.search(msg)):
        yield int(match.group(1))
    if gated and window and (match := _OPENROUTER_BREAKDOWN_RE.search(msg)):
        yield window - int(match.group(1)) - int(match.group(2))
    if gated and window and (match := _INPUT_TOKENS_RE.search(msg)):
        yield window - int(match.group(1))
    if gated and window and (match := _CHAR_PROMPT_RE.search(msg)):
        # LM Studio / llama.cpp report characters; ~3 characters per token is the conservative estimate.
        yield window - (int(match.group(1)) + 2) // 3
    if window and (match := _OPENAI_SPLIT_RE.search(msg)):
        yield window - _as_int(match.group(1))
    if match := _PASSED_INPUT_TOKENS_RE.search(msg):
        yield _as_int(match.group(2)) - _as_int(match.group(1))
    if match := _CONTEXT_SUM_RE.search(msg):
        yield _as_int(match.group(3)) - _as_int(match.group(1))


def _window_remainder(msg: str) -> int | None:
    return next((room for room in _remainder_candidates(msg) if room >= 1), None)


def parse_output_limit(exc: Exception) -> OutputLimit | None:
    """Extract the output limit a provider stated in a rejection, or None when it stated none."""
    msg = normalize_provider_error(exc).message
    if (ceiling := _model_ceiling(msg)) is not None:
        return OutputLimit(tokens=ceiling, model_cap=True)
    if (room := _window_remainder(msg)) is not None:
        return OutputLimit(tokens=room, model_cap=False)
    return None


__all__ = ["OutputLimit", "parse_output_limit"]
