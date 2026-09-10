"""Dynamic Context Assembler for Unified Memory Governance.

[INPUT]
governance.models::ProfileSlots (POS: 记忆治理领域数据模型层)
governance.models::EventTimelineItem (POS: 记忆治理领域数据模型层)
governance.models::DynamicFactItem (POS: 记忆治理领域数据模型层)
governance.models::AssembledMemoryContext (POS: 记忆治理领域数据模型层)
governance.graph_bridge::EntityGraphBridge (POS: 受限图关系扩散桥接层)

[OUTPUT]
estimate_tokens: Token 开销启发式估算函数
DynamicContextAssembler: 四维记忆上下文装配引擎

[POS]
四维记忆上下文装配引擎。执行确定性字典序前缀输出与严格 Token 预算截断。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.governance.graph_bridge import EntityGraphBridge
from myrm_agent_harness.toolkits.memory.governance.models import (
    AssembledMemoryContext,
    DynamicFactItem,
    EventTimelineItem,
    FactStatus,
    ProfileSlots,
)


def estimate_tokens(text: str) -> int:
    """Rough estimation of token count (approx. 2.5 - 3 chars per token for mixed CJK/EN)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 2.8))


class DynamicContextAssembler:
    """Four-dimensional context assembler with deterministic sorting and token budgeting."""

    def __init__(
        self,
        graph_bridge: EntityGraphBridge | None = None,
        max_total_tokens: int = 2000,
    ) -> None:
        self._graph_bridge = graph_bridge
        self._max_total_tokens = max_total_tokens

    async def assemble_context(
        self,
        profile: ProfileSlots,
        timeline: Sequence[EventTimelineItem],
        dynamic_facts: Sequence[DynamicFactItem],
        seed_entities: Sequence[str] | None = None,
        token_budget: int | None = None,
    ) -> AssembledMemoryContext:
        """Assemble a multi-dimensional context honoring token limits.

        Order of priority:
        1. User Profile Slots (Header with strict alphabetical key ordering for prompt caching).
        2. Dynamic Facts (Active, valid facts sorted by confidence and recency).
        3. Event Timeline (Recent chronological events).
        4. Entity Graph (Bounded 2-hop entity relations).
        """
        budget = token_budget or self._max_total_tokens

        # 1. Profile Prefix (Highest priority, immutable deterministic format)
        profile_text = profile.to_cached_prefix_text()
        remaining_budget = budget - estimate_tokens(profile_text)

        # 2. Dynamic Facts
        active_facts = [
            f for f in dynamic_facts if f.status == FactStatus.ACTIVE and not f.is_expired()
        ]
        # Sort by confidence descending, then by updated_at descending
        sorted_facts = sorted(
            active_facts,
            key=lambda item: (item.confidence, item.updated_at.timestamp()),
            reverse=True,
        )

        # Available budget for dynamic memory pool (Facts + Timeline)
        pool_budget = max(0, remaining_budget)
        initial_fact_quota = int(pool_budget * 0.45)
        initial_event_quota = pool_budget - initial_fact_quota

        # Pass 1: Assemble Dynamic Facts within initial quota
        fact_lines: list[str] = []
        fact_tokens = 0
        unconsumed_facts: list[DynamicFactItem] = []

        for fact in sorted_facts:
            line = f"- [{fact.category}] {fact.content}"
            cost = estimate_tokens(line)
            if fact_tokens + cost <= initial_fact_quota:
                fact_lines.append(line)
                fact_tokens += cost
            else:
                unconsumed_facts.append(fact)

        # Calculate surplus from facts (if facts used less than initial quota)
        fact_surplus = max(0, initial_fact_quota - fact_tokens)
        effective_event_quota = initial_event_quota + fact_surplus

        # Pass 2: Assemble Event Timeline with loaned budget
        sorted_events = sorted(timeline, key=lambda e: e.timestamp, reverse=True)
        event_lines: list[str] = []
        event_tokens = 0

        for event in sorted_events:
            ts_str = event.timestamp.strftime("%Y-%m-%d %H:%M")
            line = f"[{ts_str}] {event.summary}"
            if event.details:
                line += f": {event.details}"
            cost = estimate_tokens(line)
            if event_tokens + cost <= effective_event_quota:
                event_lines.append(line)
                event_tokens += cost
            else:
                break

        # Pass 3: Spill back any remaining timeline surplus to unconsumed facts
        event_surplus = max(0, effective_event_quota - event_tokens)
        if event_surplus > 0 and unconsumed_facts:
            for fact in unconsumed_facts:
                line = f"- [{fact.category}] {fact.content}"
                cost = estimate_tokens(line)
                if (fact_tokens + event_tokens + cost) <= pool_budget:
                    fact_lines.append(line)
                    fact_tokens += cost
                else:
                    break

        dynamic_facts_section = "\n".join(fact_lines)
        timeline_section = "\n".join(reversed(event_lines))
        remaining_budget = pool_budget - (fact_tokens + event_tokens)

        # 4. Entity Graph Relations
        entity_graph_section = ""
        if self._graph_bridge is not None and seed_entities and remaining_budget > 30:
            graph_text = await self._graph_bridge.get_bounded_subgraph_text(
                seed_entity_names=seed_entities,
                max_depth=2,
                max_nodes=10,
            )
            if graph_text:
                graph_cost = estimate_tokens(graph_text)
                if graph_cost <= remaining_budget:
                    entity_graph_section = graph_text
                else:
                    # Truncate lines
                    allowed_lines: list[str] = []
                    curr = 0
                    for gl in graph_text.splitlines():
                        c = estimate_tokens(gl)
                        if curr + c <= remaining_budget:
                            allowed_lines.append(gl)
                            curr += c
                        else:
                            break
                    entity_graph_section = "\n".join(allowed_lines)

        full_text = (
            profile_text
            + "\n"
            + timeline_section
            + "\n"
            + dynamic_facts_section
            + "\n"
            + entity_graph_section
        )

        return AssembledMemoryContext(
            cached_profile_prefix=profile_text,
            timeline_section=timeline_section,
            dynamic_facts_section=dynamic_facts_section,
            entity_graph_section=entity_graph_section,
            total_estimated_tokens=estimate_tokens(full_text),
        )
