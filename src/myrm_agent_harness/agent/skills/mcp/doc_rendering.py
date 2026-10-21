"""MCP SKILL.md rendering: the L2 tool-section budget ladder and its text helpers.

[INPUT]
- agent.skills.mcp.schema_doc_utils (POS: JSON Schema to signature/document rendering)
- agent.skills.mcp.tool_name_utils (POS: canonical to Python tool names)

[OUTPUT]
- cap_instructions(): bound server instructions inside the L2 ceiling
- tool_section_budget(): tokens the tool section may use after instructions
- build_tool_section(): render the L2 tool section once and report its tier
- render_tool_tier() / build_tool_index(): the individual ladder rungs
- truncate_to_sentence() / clean_markdown() / text_field(): shared text helpers

[POS]
Pure rendering layer for the generated MCP SKILL.md. Token-budget arithmetic and
the full -> required -> names degradation live here so the generator stays an
orchestrator and each concern has one implementation.
"""

from __future__ import annotations

import logging
import re

from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import (
    normalize_input_schema,
    render_signature,
)
from myrm_agent_harness.agent.skills.mcp.tool_name_utils import build_tool_name_map
from myrm_agent_harness.utils.text_utils import get_token_count

logger = logging.getLogger(__name__)

type JsonDict = dict[str, object]

INSTRUCTIONS_TOKEN_LIMIT = 2_000
"""Server instructions are capped here so one verbose server cannot blow up L2."""

L2_MAX_TOKENS = 3_000
"""Hard ceiling for one generated SKILL.md body (1.5x the 2,000-token authored band).

Every part is bounded below, so the assembled body can never exceed this.
"""

L2_FIXED_TOKENS = 224
"""Header + calling contract, measured on 12306."""

INDEX_NOTE_TOKENS = 96
"""Reserve for the tier note the generator appends after the tool section.

Covers a long server/skill name in the `/mcp/<skill>/<func>.md` pointer; the note is
only appended for the `required`/`names` tiers, so reserving the maximum keeps the
whole L2 body inside `L2_MAX_TOKENS` for every tier.
"""

MIN_TOOL_SECTION_TOKENS = L2_MAX_TOKENS - INSTRUCTIONS_TOKEN_LIMIT - L2_FIXED_TOKENS - INDEX_NOTE_TOKENS
"""Floor left for tools when instructions use their whole cap (680)."""

SIGNATURE_TOKENS_PER_TOOL = 120
"""Budget for one signature line; past it the line degrades to ``name(…)`` + a doc pointer."""

TOOL_LINE_DESC_CHARS = 60
"""Characters of tool description kept after a signature line."""


def cap_instructions(text: str, skill_name: str, limit: int) -> str:
    """Bound server-provided instructions so one verbose server cannot blow up L2.

    Cut on a sentence boundary near the token budget; the marker tells the model
    that a rule may be missing so it asks instead of inventing one.
    """
    if not text:
        return ""
    tokens = get_token_count(text)
    if tokens <= limit:
        return text
    budget = max(1, int(len(text) * limit / tokens))
    head = text[:budget]
    for separator in ("。", "\n", ". "):
        cut = head.rfind(separator)
        if cut > budget * 0.6:
            head = head[: cut + len(separator)]
            break
    logger.warning(
        "MCP instructions for '%s' truncated: %d -> about %d tokens",
        skill_name,
        tokens,
        limit,
    )
    return f"{head.rstrip()}\n\n[instructions truncated at ~{limit} tokens; ask the user when a rule is unclear]"


def text_field(schema: JsonDict, key: str, default: str) -> str:
    """Return the string stored under *key* in a tool schema, or *default* when it is absent or not a string."""
    value = schema.get(key)
    return value if isinstance(value, str) else default


def truncate_to_sentence(text: str, max_len: int = 150) -> str:
    """Truncate text at the first sentence boundary, or at max_len."""
    match = re.search(r"[。.\n]", text)
    if match and match.end() <= max_len:
        return text[: match.end()].strip()
    if len(text) > max_len:
        return text[:max_len].strip() + "..."
    return text


def clean_markdown(text: str) -> str:
    """Strip markdown formatting from text."""
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"#+\s*", "", text)
    return re.sub(r"\n+", " ", text).strip()


def tool_section_budget(instructions: str) -> int:
    """Tools get whatever the instructions leave inside the L2 ceiling, with a floor."""
    used = get_token_count(instructions) if instructions else 0
    return max(MIN_TOOL_SECTION_TOKENS, L2_MAX_TOKENS - L2_FIXED_TOKENS - INDEX_NOTE_TOKENS - used)


def build_tool_section(
    tools: list[str],
    tool_schemas: dict[str, JsonDict],
    skill_name: str,
    budget: int,
) -> tuple[str, str]:
    """Render the L2 tool section once and return it with the tier that was chosen."""
    name_map = build_tool_name_map(tools)
    for tier in ("full", "required"):
        text = render_tool_tier(tools, tool_schemas, name_map, skill_name, tier)
        if get_token_count(text) <= budget:
            return text, tier
    return build_tool_index(tools, name_map, budget), "names"


def render_tool_tier(
    tools: list[str],
    tool_schemas: dict[str, JsonDict],
    name_map: dict[str, str],
    skill_name: str,
    tier: str,
) -> str:
    """Render the tool section for one ladder tier (``full`` / ``required`` / ``names``)."""
    if tier == "names":
        return build_tool_index(tools, name_map)

    lines: list[str] = []
    for tool_name in tools:
        schema = tool_schemas.get(tool_name, {})
        func_name = name_map[tool_name]
        desc = truncate_to_sentence(text_field(schema, "description", ""), max_len=TOOL_LINE_DESC_CHARS).strip()

        signature = render_signature(
            func_name, normalize_input_schema(schema.get("inputSchema")), required_only=tier == "required"
        )
        line = f"- {signature} — {desc}" if desc else f"- {signature}"
        if get_token_count(line) > SIGNATURE_TOKENS_PER_TOOL:
            pointer = f"/mcp/{skill_name}/{func_name}.md" if skill_name else "the function doc"
            line = f"- {func_name}(…) — {desc or 'no description'}（参数见 {pointer}）"
        lines.append(line)

    return "\n".join(lines)


def build_tool_index(tools: list[str], name_map: dict[str, str], budget: int | None = None) -> str:
    """Name-only index, the last rung of the budget ladder.

    Descriptions are dropped on purpose: name-only costs 960 tokens for 100 tools
    and 2,360 for 300, while a first-sentence hint per tool would exceed the L2
    ceiling. The model reads the doc for the one or two tools it needs.

    When the hard ceiling cannot fit every name, the tail is dropped with an
    explicit count so the omission is visible instead of silent.
    """
    lines = [f"- {name_map[tool_name]}" for tool_name in tools]
    if budget is None:
        return "\n".join(lines)

    def _render(count: int) -> str:
        omitted = len(lines) - count
        suffix = f"\n[{omitted} more tools not shown; ask the user for the exact tool name]" if omitted else ""
        return "\n".join(lines[:count]) + suffix

    low, high, best = 0, len(lines), ""
    while low <= high:
        middle = (low + high) // 2
        candidate = _render(middle)
        if get_token_count(candidate) <= budget:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best or _render(0)
