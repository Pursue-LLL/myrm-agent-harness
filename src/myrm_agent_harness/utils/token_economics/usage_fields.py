"""Provider-cache token extraction shared by cost computation and usage tracking.

Different providers report the same cache quantities under different keys: LiteLLM
normalises OpenAI/Anthropic/Gemini into ``prompt_tokens_details.*``, some adapters
keep a top-level ``cache_read_tokens`` / ``cache_write_tokens`` pair, and raw
Anthropic payloads use ``cache_read_input_tokens`` / ``cache_creation_input_tokens``.
Cost computation and ``TokenTracker`` must read the same number from the same
payload, otherwise the billed cost and the reported cache hit rate disagree.

[INPUT]
- collections.abc::Mapping (POS: provider usage payloads, plain dicts or model dumps)

[OUTPUT]
- extract_cached_tokens(): prompt tokens served from the provider cache
- extract_cache_write_tokens(): prompt tokens newly written to the provider cache
- extract_cost_tokens(): (prompt, completion, cache read, cache write) for cost computation

[POS]
Single reader for provider cache accounting fields. Framework-neutral and safe for
any layer to import; the LLM adapters, the cost engine and ``TokenTracker`` all
delegate here so one payload always yields one interpretation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from myrm_agent_harness.utils.coercion import parse_int

_CACHED_KEYS = ("cached_tokens", "cache_read_tokens", "cache_read_input_tokens")
_CACHE_WRITE_KEYS = ("cache_write_tokens", "cache_creation_input_tokens")


def _prompt_details(usage: Mapping[str, object]) -> Mapping[str, object]:
    details = usage.get("prompt_tokens_details")
    return cast("Mapping[str, object]", details) if isinstance(details, Mapping) else {}


def _first_positive(sources: tuple[Mapping[str, object], ...], keys: tuple[str, ...]) -> int:
    for source in sources:
        for key in keys:
            value = parse_int(source.get(key), 0, min_val=0)
            if value:
                return value
    return 0


def extract_cached_tokens(usage: Mapping[str, object]) -> int:
    """Return the prompt tokens the provider served from its cache."""
    return _first_positive((_prompt_details(usage), usage), _CACHED_KEYS)


def extract_cache_write_tokens(usage: Mapping[str, object]) -> int:
    """Return the prompt tokens newly written to the provider cache (Anthropic billing)."""
    return _first_positive((usage, _prompt_details(usage)), _CACHE_WRITE_KEYS)


def extract_cost_tokens(usage: Mapping[str, object]) -> tuple[int, int, int, int]:
    """Return ``(prompt, completion, cache_read, cache_write)`` for cost computation."""
    return (
        parse_int(usage.get("prompt_tokens"), 0, min_val=0),
        parse_int(usage.get("completion_tokens"), 0, min_val=0),
        extract_cached_tokens(usage),
        extract_cache_write_tokens(usage),
    )
