"""Budget partitioning and prompt guidance helpers for memory context injection.

Applies token/char budgeting across stable and untrusted memory sections,
and generates static search guidance and cold-start discovery prompts.

[INPUT]
- agent.security.guards.prompt_budget::CHARS_PER_TOKEN, BudgetedSection (POS: Prompt budgeting data models)
- langchain.agents.middleware::ModelRequest (POS: Agent runtime request model)

[OUTPUT]
- partition_budget_sections: Apply unified budget and split into stable/untrusted Markdown bodies
- escape_xml_item: XML item sanitization helper
- memory_search_tool_bound: Check if memory_search_tool is bound to the request
- memory_search_guidance: Retrieve guidance text for memory search
- memory_guidance_tail: Retrieve citation and search guidance tail
- build_cold_start_context: Construct cold-start discovery prompt
- COLD_START_CONTEXT: Cached default cold-start context
- anchor_canonical_security_tokens: Extract canonical security pattern or quoted identifier from rules

[POS]
Internal helper module for memory_context_format.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.security.guards.prompt_budget import (
    CHARS_PER_TOKEN,
    BudgetedSection,
)

if TYPE_CHECKING:
    from langchain.agents.middleware import ModelRequest


def escape_xml_item(text: str) -> str:
    """Escape XML special characters for memory item text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def partition_budget_sections(
    stable_sections: list[BudgetedSection],
    escaped_untrusted_sections: list[BudgetedSection],
    *,
    max_tokens: int,
    truncation_message: str,
) -> tuple[str, str, dict[str, int]]:
    """Apply a single combined char budget; split Markdown body into stable vs untrusted halves.

    Mirrors ``PromptBudgetGuard.apply_budget`` priority ordering across both buckets so total
    memory injection cannot exceed historical single-guard semantics.

    Returns the accepted item count per section title (keyed by title) so callers can report
    how many items actually reached the model instead of how many merely exist.
    """
    tagged: list[tuple[str, BudgetedSection]] = [("stable", s) for s in stable_sections]
    tagged.extend(("untrusted", s) for s in escaped_untrusted_sections)
    tagged.sort(key=lambda t: t[1].priority)

    max_chars = max_tokens * CHARS_PER_TOKEN
    current_length = 0
    truncated = False

    stable_blocks: list[str] = []
    untrusted_blocks: list[str] = []
    accepted_by_title: dict[str, int] = {}

    for kind, section in tagged:
        if not section.items:
            continue
        header = f"## {section.title}\n"
        if current_length + len(header) > max_chars:
            truncated = True
            break
        current_length += len(header)

        accepted_lines: list[str] = []
        for item in section.items:
            line = f"- {item}\n"
            if current_length + len(line) > max_chars:
                truncated = True
                break
            accepted_lines.append(line)
            current_length += len(line)

        if not accepted_lines:
            continue

        accepted_by_title[section.title] = accepted_by_title.get(section.title, 0) + len(accepted_lines)
        block = header + "".join(accepted_lines).strip()
        if kind == "stable":
            stable_blocks.append(block)
        else:
            untrusted_blocks.append(block)

        if truncated:
            break

    stable_body = "\n\n".join(stable_blocks).strip()
    untrusted_body = "\n\n".join(untrusted_blocks).strip()

    if truncated and truncation_message:
        trimmed = truncation_message.strip()
        if untrusted_blocks:
            untrusted_body = f"{untrusted_body}\n{trimmed}" if untrusted_body else trimmed
        elif stable_blocks:
            stable_body = f"{stable_body}\n{trimmed}" if stable_body else trimmed

    return stable_body, untrusted_body, accepted_by_title


def memory_search_tool_bound(request: ModelRequest) -> bool:
    """Detect if memory_search_tool is bound to the agent request."""
    tools = getattr(request, "tools", None) or []
    for tool in tools:
        name = getattr(tool, "name", None)
        if name is None and isinstance(tool, dict):
            name = tool.get("name")
        if name == "memory_search_tool":
            return True
    return False


def memory_search_guidance(*, memory_search_enabled: bool) -> str:
    """Memory-search tool guidance; empty when the tool is not bound."""
    if not memory_search_enabled:
        return ""
    return "\n".join(
        [
            "## Memory Search",
            (
                "Use memory_search_tool with corpus=memory (default) for durable user facts, preferences, "
                "profile data, rules, and project conventions."
            ),
            (
                "Use corpus=sessions for prior chat evidence, earlier decisions, branch/fork context, "
                'or requests like "last time", "previously", and "continue that discussion". '
                "Use corpus=wiki when wiki is enabled; corpus=all searches every enabled corpus."
            ),
            (
                "Memories and recalled conversations are point-in-time records. "
                "If recalled info conflicts with current observations, trust what you see now."
            ),
        ]
    )


def memory_guidance_tail(*, memory_search_enabled: bool) -> str:
    """Shared guidance tail for warm memory contexts (citations + memory search)."""
    if not memory_search_enabled:
        return ""
    return f"""## Citation Requirements
When your answer directly relies on a memory or rule with an explicit [ID: ...] label (shown above), or on memory_search_tool results, you MUST append a citation tag at the end of the relevant sentence or paragraph.
Format: <cite:MEMORY_ID>
Example: "Based on your preference for concise answers <cite:mem-123>, here is the script."
Only cite an ID that is explicitly shown above or returned by memory_search_tool.

{memory_search_guidance(memory_search_enabled=memory_search_enabled)}"""


def build_cold_start_context(*, memory_search_enabled: bool) -> str:
    """Cold-start discovery context for a user with no memories yet."""
    return f"""<user_memory_context>
# New User — Discovery Mode

No memories yet. Actively learn about this user during the conversation:
- Note their name, role, and tech stack when mentioned
- Pay attention to how they prefer to receive information
- Observe recurring patterns in their requests
- Record explicit instructions about workflow, output format, or constraints

Use memory_store_tool to save important facts as you learn them.
{memory_guidance_tail(memory_search_enabled=memory_search_enabled)}
</user_memory_context>"""


COLD_START_CONTEXT = build_cold_start_context(memory_search_enabled=True)

# Canonical security tokens for destructive operations and sensitive files
CANONICAL_SECURITY_TOKENS: tuple[str, ...] = (
    "sudo",
    "rm -rf",
    "rm -r",
    "rm -f",
    "mkfs",
    "dd if=",
    "dd of=",
    "chmod 777",
    "chmod -R 777",
    ".env",
    "id_rsa",
    "config.yaml",
)


def anchor_canonical_security_tokens(action_str: str, trigger_str: str = "") -> str:
    """Extract a canonical security pattern or quoted identifier from natural language rules.

    If action_str or trigger_str contains an explicit canonical destructive token
    (e.g., 'sudo', 'rm -rf', '.env'), returns the matched token as a concise pattern.
    If enclosed in quotes (e.g. "don't use 'trash-cli'"), extracts the quoted identifier.
    Otherwise, returns action_str as fallback.
    """
    text = f"{action_str} {trigger_str}".strip()
    text_lower = text.lower()

    # 1. Match against canonical tokens (ordered by specificity)
    for token in CANONICAL_SECURITY_TOKENS:
        if token.lower() in text_lower:
            if token in ("sudo", "mkfs"):
                return f"{token} "
            return token

    # 2. Extract quoted identifiers (e.g. `cmd` or 'cmd' or "cmd")
    quoted = re.findall(r"['\"`]([^'\"`\s]{2,40})['\"`]", text)
    if quoted:
        return quoted[0]

    return action_str
