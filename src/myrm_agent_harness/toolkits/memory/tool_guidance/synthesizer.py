"""Pure-functional synthesizer for tool guidance evolution.

Consolidates procedural memory entries, traps, and edicts into a
deterministic, cache-stable golden guidance set for active tools.
Strictly zero-LLM cost, sub-millisecond execution, and bounded output.

[INPUT]
- myrm_agent_harness.toolkits.memory.tool_guidance.types::ToolGuidanceItem (POS: Tool memory procedural contract layer)

[OUTPUT]
- is_exploratory_probe: Pure function detecting exploratory test commands
- filter_guidance_items: Pure function filtering guidance by target tools and environment fingerprint
- synthesize_tool_guidance: Cache-stable aggregator generating up to 3 golden guidelines per tool

[POS]
Tool memory guidance synthesizer. Delivers bounded, deterministic, cache-stable prompt
guidelines by filtering noisy probe commands and ordering instructions alphabetically.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.tool_guidance.types import ToolGuidanceItem

_PROBE_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(?:command\s+-v|which|type\s+-p|test\s+-[efd]|grep\s+-q)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:\[\s+-[efd]\s+[^\]]+\])\s*$", re.IGNORECASE),
)

MAX_GUIDELINES_PER_TOOL = 3
MAX_TOTAL_TOOL_GUIDELINES = 9
MAX_CHARS_PER_GUIDELINE = 160


def is_exploratory_probe(command_text: str | None) -> bool:
    """Detect whether a command was merely a capability probe rather than a true failure.

    Probes returning non-zero exit codes (like 'command -v rustc') should
    never pollute tool guidance with negative avoidance rules.
    """
    if not command_text:
        return False
    stripped = command_text.strip()
    return any(pat.search(stripped) is not None for pat in _PROBE_COMMAND_PATTERNS)


def filter_guidance_items(
    items: Sequence[ToolGuidanceItem],
    target_tools: set[str] | None = None,
    current_env: str | None = None,
    current_agent_id: str | None = None,
) -> list[ToolGuidanceItem]:
    """Filter raw guidance items by tool relevance, host environment, and agent scope."""
    matched: list[ToolGuidanceItem] = []
    for it in items:
        if target_tools is not None and it.tool_name not in target_tools:
            continue

        if it.env_fingerprint and current_env and it.env_fingerprint != current_env:
            continue

        if it.agent_id and current_agent_id and it.agent_id != current_agent_id:
            continue

        if is_exploratory_probe(it.trigger_pattern):
            continue

        matched.append(it)
    return matched


def synthesize_tool_guidance(
    items: Sequence[ToolGuidanceItem],
    target_tools: set[str] | None = None,
    current_env: str | None = None,
    current_agent_id: str | None = None,
    max_per_tool: int = MAX_GUIDELINES_PER_TOOL,
    max_total: int = MAX_TOTAL_TOOL_GUIDELINES,
) -> dict[str, list[str]]:
    """Synthesize deterministic, cache-stable golden guidelines grouped by tool name.

    Guarantees:
    1. At most `max_per_tool` guidelines per tool (prevents per-tool bloat).
    2. At most `max_total` guidelines across all active tools (prevents context bloat).
    3. Pinned rules always take priority over dynamic self-healed rules.
    4. String length strictly bounded to `MAX_CHARS_PER_GUIDELINE`.
    5. Final guideline strings for each tool are alphabetically sorted to ensure
       100% deterministic Prompt Cache stability across calls.
    """
    filtered = filter_guidance_items(
        items,
        target_tools=target_tools,
        current_env=current_env,
        current_agent_id=current_agent_id,
    )

    by_tool: dict[str, list[ToolGuidanceItem]] = defaultdict(list)
    for it in filtered:
        by_tool[it.tool_name].append(it)

    def _sort_key(candidate: ToolGuidanceItem) -> tuple[int, float, int]:
        return (
            1 if candidate.is_pinned else 0,
            candidate.confidence,
            candidate.hit_count,
        )

    # Step 1: Per-tool pre-selection up to max_per_tool
    pre_selected: list[tuple[str, str, ToolGuidanceItem]] = []
    for tool_name in sorted(by_tool.keys()):
        tool_items = sorted(by_tool[tool_name], key=_sort_key, reverse=True)
        seen_texts: set[str] = set()
        count = 0

        for cand in tool_items:
            clean_text = cand.rule_text.strip()
            if not clean_text:
                continue
            if len(clean_text) > MAX_CHARS_PER_GUIDELINE:
                clean_text = clean_text[: MAX_CHARS_PER_GUIDELINE - 3].rstrip() + "..."

            normalized = clean_text.lower()
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)

            pre_selected.append((tool_name, clean_text, cand))
            count += 1
            if count >= max_per_tool:
                break

    # Step 2: Global budget cap if total items exceed max_total
    if len(pre_selected) > max_total:
        pre_selected.sort(key=lambda x: _sort_key(x[2]), reverse=True)
        pre_selected = pre_selected[:max_total]

    # Step 3: Group by tool and enforce alphabetical order for prompt cache stability
    grouped: dict[str, list[str]] = defaultdict(list)
    for tool_name, text, _ in pre_selected:
        grouped[tool_name].append(text)

    result: dict[str, list[str]] = {}
    for tool_name in sorted(grouped.keys()):
        result[tool_name] = sorted(grouped[tool_name])

    return result
