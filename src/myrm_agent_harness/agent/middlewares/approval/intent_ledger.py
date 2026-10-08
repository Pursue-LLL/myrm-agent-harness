"""User Intent Ledger for Reasoning-Blind approval classification.

[INPUT]
- Sequence of BaseMessage objects from conversation state, maximum character budget.

[OUTPUT]
- Curated user intent context string preserving initial task anchor, latest directives,
  multimodal text blocks, and explicitly marking omitted history or missing visible intent.

[POS]
- Harness approval middleware in agent/middlewares/approval/intent_ledger.py.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage

OMITTED_MARKER = "[earlier user messages omitted]"
NO_USER_MESSAGE_VISIBLE = "[no user message visible]"


def _extract_text_from_message_content(content: object) -> str:
    """Extract string content from string or multimodal block sequence."""
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, Sequence) and not isinstance(
        content, (str, bytes, bytearray)
    ):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                b_type = block.get("type")
                if b_type == "text" and isinstance(block.get("text"), str):
                    t = str(block.get("text")).strip()
                    if t:
                        text_parts.append(t)
        return " ".join(text_parts).strip()

    return ""


def is_user_authored_human_message(msg: BaseMessage) -> bool:
    """Determine whether a message represents authentic user input rather than synthetic runtime injection."""
    if not isinstance(msg, HumanMessage):
        return False

    kwargs = getattr(msg, "additional_kwargs", {})
    if not isinstance(kwargs, dict):
        return True

    # Explicit synthetic flag
    if kwargs.get("is_system_synthetic") is True:
        return False

    return kwargs.get("source") not in ("runtime", "system", "working_memory")


def extract_user_intent_ledger(
    messages: Sequence[BaseMessage], max_chars: int = 2500
) -> str:
    """Assemble user intent ledger with anchor retention and tail-first budget allocation.

    Rules:
    1. Only genuine user-authored HumanMessages (and approval guidance) are collected.
    2. Empty intent is explicitly formatted as `[no user message visible]` rather than None.
    3. The initial user request is anchored as the primary task directive.
    4. Recent instructions are prioritized backwards under the character budget so latest
       boundaries are never dropped by tool call turn expansion.
    5. Omitted intermediate turns are denoted with `[earlier user messages omitted]`.
    """
    user_texts: list[str] = []

    for msg in messages:
        if is_user_authored_human_message(msg):
            extracted = _extract_text_from_message_content(msg.content)
            if extracted:
                user_texts.append(extracted)

    if not user_texts:
        return NO_USER_MESSAGE_VISIBLE

    total_len = sum(len(t) for t in user_texts) + len(user_texts) - 1
    if total_len <= max_chars:
        return "\n".join(user_texts)

    # When budget is exceeded: anchor (first) and latest are strictly prioritized
    anchor = user_texts[0]
    latest = user_texts[-1]
    middle_candidates = user_texts[1:-1]

    # Baseline cost of anchor + latest + separator
    base_cost = len(anchor) + len(latest) + 1

    if base_cost >= max_chars:
        # Extreme constraint: split budget between anchor and latest
        latest_budget = min(len(latest), max_chars * 3 // 5)
        anchor_budget = max_chars - latest_budget - len(OMITTED_MARKER) - 4
        trimmed_anchor = anchor[: max(anchor_budget, 10)] + "..."
        trimmed_latest = latest[-latest_budget:]
        return f"{trimmed_anchor}\n{OMITTED_MARKER}\n{trimmed_latest}"

    # We can fully fit anchor and latest. Allocate remaining budget to middle backwards.
    budget_remaining = max_chars - base_cost - len(OMITTED_MARKER) - 2
    selected_middle: list[str] = []
    omitted_any = False

    for m in reversed(middle_candidates):
        cost = len(m) + 1
        if cost <= budget_remaining:
            selected_middle.append(m)
            budget_remaining -= cost
        else:
            omitted_any = True

    selected_middle.reverse()

    if omitted_any or middle_candidates:
        if omitted_any:
            parts = [anchor, OMITTED_MARKER]
            parts.extend(selected_middle)
            parts.append(latest)
            return "\n".join(parts)
        parts = [anchor]
        parts.extend(selected_middle)
        parts.append(latest)
        return "\n".join(parts)

    return f"{anchor}\n{latest}"
