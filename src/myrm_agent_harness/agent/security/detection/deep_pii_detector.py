"""LLM-based non-structured PII detector for deep scan mode.

Supplements regex-based PII detection (pii_classifier) with LLM-powered
semantic analysis to catch non-structured privacy types that regex cannot
match — medical conditions, political views, precise locations described
in natural language, etc.

Design:
  - Protocol-based: receives LLM call capability via ``DeepPIILLMFunc``
    — no direct dependency on any concrete LLM implementation.
  - Batch-friendly: accepts multiple texts in a single call to minimize
    LLM invocation count.
  - Fail-open: returns empty results on LLM failure (existing regex
    detection still applies as fallback).

[INPUT]
- LLM call function (protocol-based)
- PseudonymStore for mapping storage

[OUTPUT]
- DeepPIIItem: single non-structured PII detection result
- detect_deep_pii(): batch LLM-based PII detection
- pseudonymize_deep_pii(): detect + replace via PseudonymStore

[POS]
LLM-based non-structured PII detector. Batch-processes texts via LLM
with structured prompt to identify Medical Health, Political Views,
Financial Records, Precise Locations, and 15+ other semantic PII types.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from myrm_agent_harness.agent.security.detection.deep_pii_prompt import build_deep_pii_prompt
from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore
from myrm_agent_harness.utils.text_sanitizer import sanitize_text

logger = logging.getLogger(__name__)

DeepPIILLMFunc = Callable[[str, str], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class DeepPIIItem:
    """A single non-structured PII detection result from LLM."""

    original_text: str
    privacy_type: str
    privacy_level: str  # "PL2", "PL3", "PL4"


@dataclass(slots=True)
class DeepPIIResult:
    """Batch detection result for one text segment."""

    items: list[DeepPIIItem] = field(default_factory=list)
    pseudonymized_text: str = ""


async def detect_deep_pii(
    texts: list[str],
    llm_func: DeepPIILLMFunc,
    *,
    real_name: str = "",
) -> list[list[DeepPIIItem]]:
    """Detect non-structured PII in multiple texts using a single LLM call.

    Args:
        texts: List of text segments to scan.
        llm_func: Async function (system_prompt, user_prompt) -> response.
        real_name: User's real name (helps LLM distinguish own name vs third party).

    Returns:
        List of detected PII items per input text. Index-aligned with *texts*.
        Returns empty lists on LLM failure (fail-open).
    """
    if not texts:
        return []

    system_prompt = build_deep_pii_prompt()
    user_prompt = _build_user_prompt(texts, real_name)

    try:
        raw = await llm_func(system_prompt, user_prompt)
        return _parse_detection_response(raw, len(texts))
    except Exception as e:
        logger.warning("Deep PII detection failed (fail-open): %s", e)
        return [[] for _ in texts]


async def pseudonymize_deep_pii(
    texts: list[str],
    store: PseudonymStore,
    llm_func: DeepPIILLMFunc,
    *,
    real_name: str = "",
) -> list[DeepPIIResult]:
    """Detect non-structured PII and replace with pseudonyms via PseudonymStore.

    Combines LLM detection with PseudonymStore replacement in a single
    batch call. Each detected PII item gets a typed pseudonym that persists
    across sessions.

    Args:
        texts: Text segments to protect.
        store: PseudonymStore for persistent mapping.
        llm_func: Async LLM call function.
        real_name: User's real name for detection accuracy.

    Returns:
        List of DeepPIIResult (one per input text) with pseudonymized text
        and detected items.
    """
    if not texts:
        return []

    all_items = await detect_deep_pii(texts, llm_func, real_name=real_name)
    results: list[DeepPIIResult] = []

    for text, items in zip(texts, all_items, strict=False):
        if not items:
            results.append(DeepPIIResult(pseudonymized_text=text))
            continue

        replacements = _build_replacements(items, store)
        pseudonymized = _apply_replacements(text, replacements)
        results.append(DeepPIIResult(items=items, pseudonymized_text=pseudonymized))

    total = sum(len(r.items) for r in results)
    if total > 0:
        logger.info("[DEEP_PII] Pseudonymized %d non-structured PII items across %d texts", total, len(texts))

    return results


def _build_user_prompt(texts: list[str], real_name: str) -> str:
    """Build the user prompt containing texts to analyze."""
    parts: list[str] = []
    parts.append(f"User's Real Name: {real_name or '(unknown)'}\n")

    for i, text in enumerate(texts):
        parts.append(f"--- TEXT #{i + 1} ---")
        parts.append(text)
        parts.append("")

    parts.append(
        "Analyze each text above. Return a JSON array of arrays, "
        "one inner array per text (in order). Empty array [] for texts with no PII."
    )
    return "\n".join(parts)


def _parse_detection_response(raw: str, expected_count: int) -> list[list[DeepPIIItem]]:
    """Parse LLM response into per-text PII item lists."""
    raw = sanitize_text(raw).strip()

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        logger.warning("[DEEP_PII] No JSON array found in LLM response")
        return [[] for _ in range(expected_count)]

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        try:
            import json_repair  # type: ignore[import-untyped]

            data = json_repair.loads(match.group(0))
        except Exception:
            logger.warning("[DEEP_PII] Failed to parse LLM response JSON")
            return [[] for _ in range(expected_count)]

    if not isinstance(data, list):
        return [[] for _ in range(expected_count)]

    # Handle flat list (single text) vs nested list (batch)
    if data and not isinstance(data[0], list):
        data = [data]

    results: list[list[DeepPIIItem]] = []
    for i in range(expected_count):
        if i < len(data) and isinstance(data[i], list):
            items = _parse_items(data[i])
            results.append(items)
        else:
            results.append([])

    return results


def _parse_items(raw_items: list[object]) -> list[DeepPIIItem]:
    """Parse a list of raw dicts into DeepPIIItem objects."""
    items: list[DeepPIIItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        original = item.get("original_text", "")
        ptype = item.get("privacy_type", "")
        plevel = item.get("privacy_level", "")
        if original and ptype and plevel in ("PL2", "PL3", "PL4"):
            items.append(DeepPIIItem(original_text=str(original), privacy_type=str(ptype), privacy_level=str(plevel)))
    return items


def _build_replacements(items: list[DeepPIIItem], store: PseudonymStore) -> list[tuple[str, str]]:
    """Build (original, pseudonym) replacement pairs sorted by length desc."""
    replacements: list[tuple[str, str]] = []
    for item in items:
        pseudonym = store.get_or_create(
            item.original_text,
            item.privacy_type,
            item.privacy_level,
        )
        replacements.append((item.original_text, pseudonym))
    replacements.sort(key=lambda x: len(x[0]), reverse=True)
    return replacements


def _apply_replacements(text: str, replacements: list[tuple[str, str]]) -> str:
    """Apply replacements to text, longest-first to avoid partial matches."""
    for original, pseudonym in replacements:
        text = text.replace(original, pseudonym)
    return text
