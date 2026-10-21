"""Agent explicit search params → provider-specific format normalization.

[INPUT]
- (none — pure string/date transforms)

[OUTPUT]
- normalize_explicit_params: Agent time_range → Volcengine/SearxNG/Tavily override dict
- tavily_time_range_to_days: unified time_range → Tavily days parameter
- apply_tavily_site_constraint: query site: operator → LiteLLM search_domain_filter

[POS]
Layer-1 explicit param normalizer for web_search toolkit. Converts unified Agent
tool-call params to provider-specific extra_params before intent/config fusion.
"""

from __future__ import annotations

import re
from datetime import date

_TIME_RANGE_MAP_VOLCENGINE: dict[str, str] = {
    "day": "OneDay",
    "week": "OneWeek",
    "month": "OneMonth",
    "year": "OneYear",
}

_TAVILY_TIME_RANGE_DAYS: dict[str, str] = {
    "day": "1",
    "week": "7",
    "month": "30",
    "year": "365",
}

_TAVILY_MAX_DAYS = 365

_SITE_OPERATOR_PATTERN = re.compile(r"\bsite:([^\s]+)", re.IGNORECASE)

ProviderOverride = dict[str, str | int | bool | list[str]]


def tavily_time_range_to_days(time_range: str) -> str:
    """Convert unified time_range to Tavily 'days' parameter."""
    mapped = _TAVILY_TIME_RANGE_DAYS.get(time_range)
    if mapped is not None:
        return mapped

    if ".." in time_range:
        start_raw, _, end_raw = time_range.partition("..")
        try:
            start = date.fromisoformat(start_raw.strip())
            end = date.fromisoformat(end_raw.strip())
        except ValueError:
            return "7"
        span_days = (end - start).days + 1
        if span_days < 1:
            return "7"
        return str(min(span_days, _TAVILY_MAX_DAYS))

    return "7"


def apply_tavily_site_constraint(
    query: str,
    override: ProviderOverride | None,
) -> tuple[str, ProviderOverride | None]:
    """Map site: operators in query to LiteLLM search_domain_filter for Tavily."""
    domains = _SITE_OPERATOR_PATTERN.findall(query)
    if not domains:
        return query, override

    cleaned_query = _SITE_OPERATOR_PATTERN.sub("", query)
    cleaned_query = " ".join(cleaned_query.split()).strip()
    if not cleaned_query:
        cleaned_query = query

    merged: ProviderOverride = dict(override or {})
    existing = merged.get("search_domain_filter")
    domain_list: list[str] = []
    if isinstance(existing, list):
        domain_list.extend(str(item) for item in existing if str(item).strip())

    for raw_domain in domains:
        domain = raw_domain.strip().strip("/")
        if domain and domain not in domain_list:
            domain_list.append(domain)

    if domain_list:
        merged["search_domain_filter"] = domain_list

    return cleaned_query, merged or None


def normalize_explicit_params(
    explicit_params: dict[str, object],
    provider: str,
) -> dict[str, str | int] | None:
    """Normalize Agent-level explicit params to provider-specific format.

    Three-priority fusion model:
      1. explicit_params (highest) — from Agent tool call
      2. intent_optimizer auto-detection — from keyword regex
      3. config.extra_params (lowest) — user/admin default

    This function only handles layer 1 → provider-specific format.
    """
    if not explicit_params:
        return None

    result: dict[str, str | int] = {}
    time_range = explicit_params.get("time_range")

    if provider == "volcengine_doubao":
        if isinstance(time_range, str) and time_range:
            mapped = _TIME_RANGE_MAP_VOLCENGINE.get(time_range)
            if mapped:
                result["TimeRange"] = mapped
            elif ".." in time_range:
                result["TimeRange"] = time_range
    elif provider == "searxng":
        if isinstance(time_range, str) and time_range:
            result["time_range"] = time_range
    elif provider == "tavily" and isinstance(time_range, str) and time_range:
        result["days"] = tavily_time_range_to_days(time_range)

    return result or None


__all__ = [
    "apply_tavily_site_constraint",
    "normalize_explicit_params",
    "tavily_time_range_to_days",
]
