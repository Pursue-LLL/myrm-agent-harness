"""Safety termination detection for LLM responses.

Detects when a provider stops generation for safety reasons (e.g. content_filter,
refusal, SAFETY) while the response still carries truncated tool_calls. Without
this protection, half-formed tool arguments (like a truncated write_file) would
be dispatched as if complete, causing file corruption or infinite retry loops.

[INPUT]
- (none — pure utility, no internal dependencies)

[OUTPUT]
- SAFETY_FINISH_REASONS: frozenset of all known safety termination signals
- detect_safety_termination(): check if a finish_reason indicates safety termination
- suppress_tool_calls_for_safety(): strip tool_calls and append explanation

[POS]
Safety termination detector. Provides zero-config protection against executing
truncated tool calls when providers safety-terminate mid-generation.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# All known safety termination finish_reason values across major providers.
# OpenAI/Moonshot/DeepSeek: "content_filter"
# Anthropic: "refusal"
# Gemini: "SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION", "IMAGE_SAFETY"
SAFETY_FINISH_REASONS: frozenset[str] = frozenset(
    {
        "content_filter",
        "refusal",
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "RECITATION",
        "IMAGE_SAFETY",
    }
)


def detect_safety_termination(finish_reason: str | None) -> bool:
    """Check if the finish_reason indicates a provider safety termination."""
    return finish_reason in SAFETY_FINISH_REASONS


_USER_FACING_MESSAGE = (
    "[Safety] The model provider terminated this response due to safety filters "
    "({reason!r}). Any tool calls in this turn were suppressed because their "
    "arguments may be truncated. Please rephrase your request."
)


def suppress_tool_calls_for_safety(
    aggregated_message: dict[str, object],
    finish_reason: str,
) -> int:
    """Strip tool calls from aggregated message and append safety explanation.

    Covers both executable ``tool_calls`` and calls that the truncation gate
    already withheld into ``tool_call_recovery`` (``safe=False``): in either case
    the provider stopped mid-generation, so the model must not be asked to retry
    and the user must see why. Returns the number of suppressed calls for audit
    logging.
    """
    tool_calls = aggregated_message.get("tool_calls")
    withheld = aggregated_message.get("tool_call_recovery")
    if not isinstance(tool_calls, list) and not isinstance(withheld, list):
        return 0

    if isinstance(tool_calls, list) and tool_calls:
        suppressed_count = len(tool_calls)
        suppressed_names = [
            tc.get("function", {}).get("name", "unknown") if isinstance(tc, dict) else "unknown" for tc in tool_calls
        ]
    else:
        withheld_items = withheld if isinstance(withheld, list) else []
        suppressed_count = len(withheld_items)
        suppressed_names = [
            item.get("tool_name", "unknown") if isinstance(item, dict) else "unknown" for item in withheld_items
        ]

    aggregated_message.pop("tool_calls", None)
    aggregated_message.pop("tool_call_recovery", None)

    # Also clear raw provider payloads that some adapters preserve
    additional_kwargs = aggregated_message.get("additional_kwargs")
    if isinstance(additional_kwargs, dict):
        additional_kwargs.pop("tool_calls", None)
        additional_kwargs.pop("function_call", None)

    explanation = _USER_FACING_MESSAGE.format(reason=finish_reason)
    existing_content = aggregated_message.get("content", "")
    if existing_content:
        aggregated_message["content"] = f"{existing_content}\n\n{explanation}"
    else:
        aggregated_message["content"] = explanation

    logger.warning(
        "[SafetyTermination] Suppressed %d tool call(s): %s (reason: %s)",
        suppressed_count,
        suppressed_names,
        finish_reason,
    )

    return suppressed_count
