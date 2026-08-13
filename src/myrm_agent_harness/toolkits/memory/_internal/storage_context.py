"""Context loading for agent prompt injection.

[INPUT]
- memory.protocols.relational::RelationalStoreProtocol (POS: relational persistence)
- memory.types::{ProfileEntry, ProceduralMemory, RuleSource, TOOL_FAILURE_ORIGIN, ToolRulePriority} (POS: memory data models)

[OUTPUT]
- load_context: Loads profile, rules, and working state for agent prompt
- WORKING_STATE_PROFILE_KEY, WORKING_STATE_UPDATED_AT_KEY, WORKING_STATE_TTL_DAYS: Constants

[POS]
Context loading for agent system prompt injection. Fetches user profile entries,
active rules, agent self-instructions, and working state from relational storage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.types import (
    ProceduralMemory,
    ProfileEntry,
    RuleSource,
    TOOL_FAILURE_ORIGIN,
    ToolRulePriority,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.relational import RelationalStoreProtocol

logger = logging.getLogger(__name__)

WORKING_STATE_PROFILE_KEY = "__working_state"
WORKING_STATE_UPDATED_AT_KEY = "__working_state_updated_at"
WORKING_STATE_TTL_DAYS = 7


async def load_context(
    relational: RelationalStoreProtocol,
    *,
    include_profile: bool = True,
    include_rules: bool = True,
    include_agent_instructions: bool = True,
    namespaces: list[str] | None = None,
) -> dict[str, object]:
    ctx: dict[str, object] = {"global_profile": {}, "peer_profile": {}, "rules": [], "agent_instructions": []}

    tasks: dict[str, asyncio.Task[object]] = {}
    if include_profile:
        tasks["profile"] = asyncio.create_task(relational.list_profiles(namespaces=namespaces))
    if include_rules:
        tasks["rules"] = asyncio.create_task(relational.list_rules(active_only=True, namespaces=namespaces))

    results = dict(
        zip(
            tasks.keys(),
            await asyncio.gather(*tasks.values(), return_exceptions=True),
            strict=True,
        )
    )

    if "profile" in results and not isinstance(results["profile"], Exception):
        entries = results["profile"]
        if isinstance(entries, list):
            global_profile = {}
            peer_profile = {}
            working_state: str | None = None
            working_state_updated_at: str | None = None
            for e in entries:
                if not isinstance(e, ProfileEntry):
                    continue
                if e.key == WORKING_STATE_PROFILE_KEY:
                    working_state = e.value
                    continue
                if e.key == WORKING_STATE_UPDATED_AT_KEY:
                    working_state_updated_at = e.value
                    continue
                if e.scope.primary_namespace == "global":
                    global_profile[e.key] = e.value
                else:
                    peer_profile[e.key] = e.value
            ctx["global_profile"] = global_profile
            ctx["peer_profile"] = peer_profile

            if working_state and working_state_updated_at:
                try:
                    updated_at = datetime.fromisoformat(working_state_updated_at)
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=UTC)
                    if (datetime.now(UTC) - updated_at).days < WORKING_STATE_TTL_DAYS:
                        ctx["working_state"] = working_state
                except (ValueError, TypeError):
                    ctx["working_state"] = working_state
            elif working_state:
                ctx["working_state"] = working_state

    if "rules" in results and not isinstance(results["rules"], Exception):
        rules_raw = results["rules"]
        user_rules: list[dict[str, str | int]] = []
        agent_instrs: list[dict[str, str | int]] = []
        if isinstance(rules_raw, list):
            for r in rules_raw:
                if isinstance(r, ProceduralMemory):
                    if r.source == RuleSource.AGENT_SELF:
                        origin = r.metadata.get("origin", "")
                        if (
                            origin == TOOL_FAILURE_ORIGIN
                            and r.tool_rule_priority == ToolRulePriority.NORMAL
                            and not r.is_user_locked
                        ):
                            # Auto-generated failure rules are transient advisories:
                            # keep them out of the stable prompt layer so a momentary
                            # tool failure cannot permanently steer tool selection.
                            # They remain recallable via memory_search_tool.
                            # User-edited (locked) rules are explicitly endorsed, so
                            # they graduate into the stable layer.
                            continue
                        agent_instrs.append({"instruction": r.action, "priority": r.priority})
                    else:
                        user_rules.append(
                            {
                                "trigger": r.trigger,
                                "action": r.action,
                                "priority": r.priority,
                            }
                        )
        ctx["rules"] = user_rules
        if include_agent_instructions:
            ctx["agent_instructions"] = agent_instrs

    return ctx
