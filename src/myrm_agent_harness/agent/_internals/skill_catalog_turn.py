"""Per-turn delivery of the bound skills catalog and sync of the ``skill_search`` index.

[INPUT]
- agent._internals.turn_history::TurnHistory (POS: whether the turn rebuilds the conversation or extends the thread)
- agent.skills.runtime.skill_catalog_delivery (POS: baseline / update block rendering and thread inspection)
- agent.meta_tools.discover_capability.discover_capability_tool::sync_discover_capability_tool (POS: mounts or removes skill_search_tool)
- agent.skill_agent.context::set_bound_skills_receipt (POS: bound skills of the turn for turn-end metadata)

[OUTPUT]
- CatalogDelivery: what the turn delivered and whether the tool array changed
- deliver_bound_skills_catalog(): baseline on a rebuilt conversation, tail update on a continued thread
- sync_bound_skills_for_resume(): refresh the skill_search index before a HITL resume (messages untouched)

[POS]
Turn-prep seam between ``agent_runtime.run_agent_loop`` and the catalog delivery module. Two
fingerprints keep two concerns apart: the rendered catalog hash (read from the thread) decides
whether an update message is due, the bound-set fingerprint (kept on the agent) decides whether the
``skill_search`` index must be rebuilt.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.skills.runtime.skill_catalog_delivery import (
    ensure_skill_catalog_in_messages,
    first_human_index,
    plan_catalog_update,
    prepend_catalog_update,
    render_bound_skills_catalog,
    strip_catalog_blocks_from_message,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.agent._internals.turn_history import TurnHistory
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.skill_agent import SkillAgent
    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = get_agent_logger(__name__)

CatalogAction = Literal["none", "skipped", "baseline", "update", "unchanged"]


@dataclass(frozen=True, slots=True)
class CatalogDelivery:
    """Outcome of the catalog step of a turn.

    ``skipped``: the bound skills could not be loaded, nothing was delivered and the thread's
    last-delivered catalog stands. ``tools_changed``: mounting or removing ``skill_search_tool``
    changed the tool array, which invalidates the provider cache of the whole prefix.
    """

    action: CatalogAction
    tools_changed: bool = False

    def telemetry(self) -> dict[str, int | str]:
        facts: dict[str, int | str] = {"catalog_delivery": self.action}
        if self.tools_changed:
            facts["tools_signature_changes"] = 1
        return facts


def _skill_agent_with_backend(agent_state: BaseAgent) -> SkillAgent | None:
    from myrm_agent_harness.agent.skill_agent import SkillAgent

    if isinstance(agent_state, SkillAgent) and agent_state.skill_backend is not None:
        return agent_state
    return None


def _bound_set_fingerprint(skills: list[SkillMetadata]) -> str:
    """Identity of everything the ``skill_search`` index and its mount decision are built from."""
    rows = sorted(
        "\x1f".join(
            (
                skill.name,
                skill.description,
                skill.storage_skill_id or "",
                str(skill.available),
                str(skill.model_invocable),
                str(skill.always),
            )
        )
        for skill in skills
    )
    return hashlib.sha256("\x1e".join(rows).encode("utf-8")).hexdigest()[:16]


def _sync_skill_search_index(agent_state: SkillAgent, bound_skills: list[SkillMetadata]) -> bool:
    """Rebuild or remove ``skill_search_tool`` when the bound set changed; True when the tool array changed."""
    fingerprint = _bound_set_fingerprint(bound_skills)
    if fingerprint == agent_state._synced_skill_fingerprint:
        return False

    registry = agent_state._tool_registry
    if registry is None:
        return False

    from myrm_agent_harness.agent._internals._agent_build import _weave_dynamic_schemas
    from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
        sync_discover_capability_tool,
    )
    from myrm_agent_harness.agent.middlewares._session_context import set_active_resolved_tools
    from myrm_agent_harness.agent.tool_management.tool_layers import (
        get_tool_layer,
        get_tool_registry_sort_key,
    )

    tools_before = tuple(tool.name for tool in agent_state._cached_tools or ())
    sync_discover_capability_tool(
        registry,
        skills=bound_skills,
        skill_configs=getattr(agent_state, "skill_configs", None),
        available_tool_names=getattr(agent_state, "_available_tool_names", None),
        available_tool_groups=getattr(agent_state, "_available_tool_groups", None),
        embedding_config=getattr(agent_state, "_embedding_config", None),
        embedding_cache=getattr(agent_state, "_embedding_cache", None),
    )
    agent_state._cached_tools = _weave_dynamic_schemas(registry.resolve())
    agent_state._cached_tools.sort(key=lambda tool: get_tool_registry_sort_key(tool.name, get_tool_layer(tool.name)))
    set_active_resolved_tools(agent_state._cached_tools)
    agent_state._synced_skill_fingerprint = fingerprint

    tools_changed = tools_before != tuple(tool.name for tool in agent_state._cached_tools)
    logger.debug("skill_search index synced (%d bound skills, tools_changed=%s)", len(bound_skills), tools_changed)
    return tools_changed


def _deliver_update(
    messages: list[BaseMessage],
    agent_state: SkillAgent,
    bound_skills: list[SkillMetadata],
    history: TurnHistory,
) -> CatalogAction:
    """Prepend an update to the new HumanMessage when the thread's last-delivered catalog is out of date."""
    first_idx = first_human_index(messages)
    if first_idx is None:
        return "none"

    rendered = render_bound_skills_catalog(
        bound_skills,
        skill_configs=agent_state.skill_configs,
        available_tool_names=agent_state._available_tool_names,
        available_tool_groups=agent_state._available_tool_groups,
    )
    update_block = plan_catalog_update(history.thread_messages, rendered)
    new_message = messages[first_idx]
    assert isinstance(new_message, HumanMessage)
    if update_block is None:
        messages[first_idx] = strip_catalog_blocks_from_message(new_message)
        return "unchanged"
    messages[first_idx] = prepend_catalog_update(new_message, update_block)
    return "update"


async def deliver_bound_skills_catalog(
    messages: list[BaseMessage],
    agent_state: BaseAgent,
    history: TurnHistory,
) -> CatalogDelivery:
    """Deliver the bound skills catalog for a new-message turn.

    A rebuilt conversation (``append`` / ``replace``) gets the baseline on its first HumanMessage.
    A continued thread keeps the baseline it has and gets an update on the new HumanMessage when the
    rendered catalog drifted from what the thread last delivered. A failed skill load delivers
    nothing: the thread's last-delivered catalog stands and the next turn tries again.
    """
    skill_agent = _skill_agent_with_backend(agent_state)
    if skill_agent is None:
        return CatalogDelivery(action="none")

    from myrm_agent_harness.agent.skill_agent.context import set_bound_skills_receipt

    bound_skills = await skill_agent._load_bound_skills()
    if bound_skills is None:
        # An unknown bind list reports no bound skills rather than a stale one.
        set_bound_skills_receipt([])
        ensure_skill_catalog_in_messages(messages, [])
        return CatalogDelivery(action="skipped")

    set_bound_skills_receipt(bound_skills)
    tools_changed = _sync_skill_search_index(skill_agent, bound_skills)

    if history.mode == "continue":
        return CatalogDelivery(
            action=_deliver_update(messages, skill_agent, bound_skills, history),
            tools_changed=tools_changed,
        )

    ensure_skill_catalog_in_messages(
        messages,
        bound_skills,
        skill_configs=skill_agent.skill_configs,
        available_tool_names=skill_agent._available_tool_names,
        available_tool_groups=skill_agent._available_tool_groups,
    )
    return CatalogDelivery(action="baseline", tools_changed=tools_changed)


async def sync_bound_skills_for_resume(agent_state: BaseAgent) -> None:
    """Refresh the bound-skills receipt and ``skill_search`` index before a HITL resume.

    The thread's messages are left alone: a bind-list drift during the pause reaches the model
    as an update on the next new message.
    """
    skill_agent = _skill_agent_with_backend(agent_state)
    if skill_agent is None:
        return
    from myrm_agent_harness.agent.skill_agent.context import set_bound_skills_receipt

    bound_skills = await skill_agent._load_bound_skills()
    if bound_skills is None:
        set_bound_skills_receipt([])
        return

    set_bound_skills_receipt(bound_skills)
    _sync_skill_search_index(skill_agent, bound_skills)


__all__ = [
    "CatalogDelivery",
    "deliver_bound_skills_catalog",
    "sync_bound_skills_for_resume",
]
