"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations



from myrm_agent_harness.toolkits.memory._manager.shared import (
    AnyMemory,
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
    Sequence,
    UTC,
    datetime,
    doc_to_semantic,
    load_context,
    update_vector_memory,
)


class MemoryManagerRetrievalWriteMixin:
    async def store(self, memory: AnyMemory, *, _bypass_approval: bool = False) -> AnyMemory:
        result = await self._writer.store(memory, bypass_approval=_bypass_approval)
        self._stores_since_consolidation += 1
        trigger = self._config.consolidation.message_count_trigger
        if trigger > 0 and self._stores_since_consolidation >= trigger:
            self._stores_since_consolidation = 0
            self._maybe_consolidate()
        await self._submit_preference_candidate(result)
        return result

    async def store_batch(self, memories: Sequence[AnyMemory], *, _bypass_approval: bool = False) -> list[AnyMemory]:
        result = await self._writer.store_batch(memories, bypass_approval=_bypass_approval)
        self._stores_since_consolidation += len(memories)
        trigger = self._config.consolidation.message_count_trigger
        if trigger > 0 and self._stores_since_consolidation >= trigger:
            self._stores_since_consolidation = 0
            self._maybe_consolidate()
        for mem in result:
            await self._submit_preference_candidate(mem)
        return result

    async def search(
        self,
        query: str,
        *,
        memory_types: list[MemoryType] | None = None,
        limit: int = 10,
        use_rrf: bool = True,
        include_raw: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[MemorySearchResult]:
        session_chat_id = self._active_session.chat_id if self._active_session else None
        return await self._search_service.search(
            query,
            memory_types=memory_types or self.get_enabled_types(),
            memory_types_unspecified=memory_types is None,
            limit=limit,
            use_rrf=use_rrf,
            include_raw=include_raw,
            since=since,
            until=until,
            current_chat_id=session_chat_id,
        )

    async def get_context(
        self,
        *,
        include_profile: bool = True,
        include_rules: bool = True,
        include_agent_instructions: bool = True,
    ) -> dict[str, object]:
        if not self.has_relational:
            return {"global_profile": {}, "peer_profile": {}, "rules": [], "agent_instructions": []}
        assert self._relational is not None
        ctx = await load_context(
            self._relational,
            include_profile=include_profile,
            include_rules=include_rules,
            include_agent_instructions=include_agent_instructions,
            namespaces=self._namespaces,
        )

        return ctx

    async def get_learned_context(self) -> dict[str, list[dict[str, str]]]:
        """Retrieve auto-extracted memories for always-on injection.

        Returns preference-bearing SemanticMemories and active ProceduralMemories,
        sorted by importance and truncated to max_learned_context_chars.

        When PreferenceStabilityStrategy is active, uses stability-verified Active
        preferences instead of raw vector scroll for higher precision.
        """
        rules_task = (
            asyncio.create_task(self._relational.list_rules(active_only=True, limit=50, namespaces=self._namespaces))
            if self._relational
            else None
        )

        preference_strategy = self._preference_strategy
        use_stability = preference_strategy is not None
        docs_task = (
            asyncio.create_task(
                self._vector.scroll(
                    self._config.semantic_collection,
                    limit=200,
                    filters={"archived": False, "namespaces": self._namespaces},
                )
            )
            if self._vector and not use_stability
            else None
        )

        rules: list[ProceduralMemory] = []
        if rules_task:
            try:
                rules = await rules_task
            except Exception as e:
                logger.warning("Learned context rules query error: %s", e)

        preferences: list[SemanticMemory] = []
        if preference_strategy is not None:
            try:
                active_facets = await preference_strategy.get_active_preferences()
                for facet in active_facets:
                    pref = SemanticMemory(
                        id=facet.id,
                        content=facet.value,
                        preference_type=facet.cue.value,
                        preference_strength=min(facet.stability / 2.0, 1.0),
                        importance=0.8,
                    )
                    preferences.append(pref)
            except Exception as e:
                logger.warning("Learned context stability preferences error: %s", e)
        elif docs_task:
            try:
                docs, _ = await docs_task
                for d in docs:
                    meta = d.metadata
                    if meta.get("preference_type") not in ("explicit", "implicit"):
                        continue
                    try:
                        strength = float(meta.get("preference_strength", 0))
                    except (TypeError, ValueError):
                        continue
                    if strength > 0:
                        preferences.append(doc_to_semantic(d))
            except Exception as e:
                logger.warning("Learned context preferences query error: %s", e)

        rules.sort(key=lambda r: r.priority, reverse=True)
        preferences.sort(key=lambda m: m.importance * m.preference_strength, reverse=True)

        base_budget = self._config.max_learned_context_chars
        if self._config.model_context_tokens:
            budget = max(base_budget, self._config.model_context_tokens // 30)
        else:
            budget = base_budget
        used = 0

        learned_rules: list[dict[str, str]] = []
        for rule in rules:
            entry_len = len(rule.trigger) + len(rule.action) + 20
            if used + entry_len > budget:
                break
            entry: dict[str, str] = {
                "id": rule.id,
                "trigger": rule.trigger,
                "action": rule.action,
                "created_at": rule.created_at.isoformat(),
            }
            if hasattr(rule, "reasoning") and rule.reasoning:
                entry["reasoning"] = rule.reasoning
            if hasattr(rule, "application") and rule.application:
                entry["application"] = rule.application
            if rule.tool_name:
                entry["tool_name"] = rule.tool_name
            if rule.tool_rule_priority:
                entry["tool_rule_priority"] = rule.tool_rule_priority.value
            learned_rules.append(entry)
            used += entry_len

        corrections = [p for p in preferences if p.source_error]
        normal_prefs = [p for p in preferences if not p.source_error]
        corrections.sort(key=lambda m: m.created_at, reverse=True)

        learned_prefs: list[dict[str, str]] = []
        max_corrections = self._config.max_corrections
        for correction_count, pref in enumerate(corrections):
            if correction_count >= max_corrections or used + len(pref.content) > budget:
                break
            learned_prefs.append(
                {
                    "id": pref.id,
                    "content": pref.content,
                    "type": pref.preference_type or "implicit",
                    "source_error": pref.source_error or "",
                    "created_at": pref.created_at.isoformat(),
                }
            )
            used += len(pref.content)

        for pref in normal_prefs:
            if used + len(pref.content) > budget:
                break
            learned_prefs.append(
                {
                    "id": pref.id,
                    "content": pref.content,
                    "type": pref.preference_type or "implicit",
                    "created_at": pref.created_at.isoformat(),
                }
            )
            used += len(pref.content)

        return {"learned_rules": learned_rules, "learned_preferences": learned_prefs}

    async def get_tool_rules(
        self,
        tool_name: str,
        *,
        limit: int = 30,
    ) -> list[ProceduralMemory]:
        """Retrieve active procedural rules scoped to a specific tool."""
        if not self._relational:
            return []
        try:
            return await self._relational.list_rules_by_tool(
                tool_name, active_only=True, limit=limit, namespaces=self._namespaces
            )
        except Exception as e:
            logger.warning("get_tool_rules failed for %s: %s", tool_name, e)
            return []

    async def record_citations(self, memory_ids: list[str]) -> int:
        """Explicitly record LLM citations for lifecycle decay tracking.

        Bumps the access_count and last_accessed_at for the cited memories.
        Returns the number of successfully updated memories.
        """
        if not memory_ids:
            return 0

        updated_count = 0
        now = datetime.now(UTC)
        for mem_id in memory_ids:
            try:
                mem = await self.get_memory(mem_id)
                if not mem:
                    continue
                mem.access_count += 1
                mem.last_accessed_at = now
                if hasattr(mem, "memory_type"):
                    await self.update_memory(mem.id)  # Update just saves it via model_copy
                    # Actually update_memory does not take access_count as kwarg.
                    # Let's bypass update_memory and use the writer directly for this internal bump.
                    if isinstance(mem, (SemanticMemory, EpisodicMemory)):
                        v, e = self._vec()
                        await update_vector_memory(
                            self._bind_scope(mem),
                            False,
                            v,
                            self._config,
                            e,
                            self._cache,
                        )
                    elif isinstance(mem, ProceduralMemory):
                        await self._rel().update_rule(mem.id, mem)
                    updated_count += 1
            except Exception as e:
                logger.warning("Failed to record citation for memory %s: %s", mem_id, e)

        return updated_count
