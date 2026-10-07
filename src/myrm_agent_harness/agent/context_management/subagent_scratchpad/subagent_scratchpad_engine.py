"""多代理共享草稿白板、子代理瞬态上下文隔离与轻量事实广播核心引擎。

[INPUT]
- subagent_scratchpad_types.py: 契约模型 (FactCategory, SubagentLifecycleStatus, SharedScratchpadFact, EphemeralSubagentDossier, ScratchpadQueryFilter)

[OUTPUT]
- MultiAgentSharedScratchpadEngine:
  - register_subagent: 注册子代理并创建瞬态隔离沙箱档案
  - record_transient_log: 记录子代理瞬态执行排错日志
  - post_shared_fact: 向共享白板广播阶段性发现或已踩坑路线
  - query_shared_facts: 检索集群白板已知事实防重复试错
  - garbage_collect_subagent: 彻底销毁子代理瞬态日志完成垃圾回收

[POS]
- 位于 context_management/subagent_scratchpad/subagent_scratchpad_engine.py
"""

from datetime import datetime, timezone
import uuid

from .subagent_scratchpad_types import (
    EphemeralSubagentDossier,
    FactCategory,
    ScratchpadQueryFilter,
    SharedScratchpadFact,
    SubagentLifecycleStatus,
)


class MultiAgentSharedScratchpadEngine:
    """多代理并发共享草稿白板与瞬态沙箱生命周期治理引擎。"""

    def __init__(self) -> None:
        # cluster_id -> {fact_key: SharedScratchpadFact}
        self._cluster_facts: dict[str, dict[str, SharedScratchpadFact]] = {}
        # subagent_id -> EphemeralSubagentDossier
        self._dossiers: dict[str, EphemeralSubagentDossier] = {}
        # subagent_id -> list of transient log strings (待GC销毁的隔离日志)
        self._transient_logs: dict[str, list[str]] = {}

    def register_subagent(
        self,
        subagent_id: str,
        cluster_id: str,
        role_name: str,
    ) -> EphemeralSubagentDossier:
        """注册子代理并开辟瞬态隔离上下文空间。"""
        now_iso = datetime.now(timezone.utc).isoformat()
        dossier = EphemeralSubagentDossier(
            subagent_id=subagent_id,
            cluster_id=cluster_id,
            role_name=role_name,
            status=SubagentLifecycleStatus.ACTIVE,
            transient_logs_count=0,
            promoted_fact_ids=(),
            registered_at_iso=now_iso,
        )
        self._dossiers[subagent_id] = dossier
        self._transient_logs[subagent_id] = []

        if cluster_id not in self._cluster_facts:
            self._cluster_facts[cluster_id] = {}

        return dossier

    def record_transient_log(self, subagent_id: str, log_message: str) -> None:
        """记录子代理在执行过程中的内部瞬态调试日志（属于隔离数据，不会污染主代理）。"""
        if subagent_id in self._transient_logs:
            self._transient_logs[subagent_id].append(log_message)
            existing = self._dossiers.get(subagent_id)
            if existing:
                self._dossiers[subagent_id] = EphemeralSubagentDossier(
                    subagent_id=existing.subagent_id,
                    cluster_id=existing.cluster_id,
                    role_name=existing.role_name,
                    status=existing.status,
                    transient_logs_count=len(self._transient_logs[subagent_id]),
                    promoted_fact_ids=existing.promoted_fact_ids,
                    registered_at_iso=existing.registered_at_iso,
                    collected_at_iso=existing.collected_at_iso,
                )

    def post_shared_fact(
        self,
        cluster_id: str,
        subagent_id: str,
        category: FactCategory,
        key: str,
        summary: str,
        details: str = "",
        confidence: float = 1.0,
    ) -> SharedScratchpadFact:
        """向共享白板写入/广播关键已证伪路线、踩坑记录或公共结论。"""
        fact_id = f"fact_{uuid.uuid4().hex[:10]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        fact = SharedScratchpadFact(
            fact_id=fact_id,
            cluster_id=cluster_id,
            category=category,
            key=key,
            summary=summary,
            details=details,
            discovered_by_subagent_id=subagent_id,
            confidence=max(0.0, min(1.0, confidence)),
            created_at_iso=now_iso,
        )

        if cluster_id not in self._cluster_facts:
            self._cluster_facts[cluster_id] = {}
        self._cluster_facts[cluster_id][key] = fact

        # 更新子代理提升记录
        dossier = self._dossiers.get(subagent_id)
        if dossier:
            self._dossiers[subagent_id] = EphemeralSubagentDossier(
                subagent_id=dossier.subagent_id,
                cluster_id=dossier.cluster_id,
                role_name=dossier.role_name,
                status=dossier.status,
                transient_logs_count=dossier.transient_logs_count,
                promoted_fact_ids=dossier.promoted_fact_ids + (fact_id,),
                registered_at_iso=dossier.registered_at_iso,
                collected_at_iso=dossier.collected_at_iso,
            )

        return fact

    def query_shared_facts(
        self,
        cluster_id: str,
        filter_spec: ScratchpadQueryFilter | None = None,
    ) -> tuple[SharedScratchpadFact, ...]:
        """检索指定集群白板中已沉淀的事实（供并发子代理在动手前查阅，消灭重复试错）。"""
        cluster_map = self._cluster_facts.get(cluster_id, {})
        facts = list(cluster_map.values())

        if not filter_spec:
            return tuple(facts)

        filtered: list[SharedScratchpadFact] = []
        for f in facts:
            if filter_spec.category and f.category != filter_spec.category:
                continue
            if f.confidence < filter_spec.min_confidence:
                continue
            if filter_spec.keyword:
                kw = filter_spec.keyword.lower()
                if kw not in f.key.lower() and kw not in f.summary.lower() and kw not in f.details.lower():
                    continue
            filtered.append(f)

        return tuple(filtered)

    def garbage_collect_subagent(self, subagent_id: str) -> EphemeralSubagentDossier:
        """任务完成时触发垃圾回收：彻底销毁子代理海量瞬态排错日志，绝不回灌主会话。"""
        dossier = self._dossiers.get(subagent_id)
        if not dossier:
            raise KeyError(f"子代理 {subagent_id} 不存在。")

        # 彻底清空瞬态调试日志
        if subagent_id in self._transient_logs:
            self._transient_logs[subagent_id].clear()
            del self._transient_logs[subagent_id]

        now_iso = datetime.now(timezone.utc).isoformat()
        collected_dossier = EphemeralSubagentDossier(
            subagent_id=dossier.subagent_id,
            cluster_id=dossier.cluster_id,
            role_name=dossier.role_name,
            status=SubagentLifecycleStatus.GARBAGE_COLLECTED,
            transient_logs_count=0,
            promoted_fact_ids=dossier.promoted_fact_ids,
            registered_at_iso=dossier.registered_at_iso,
            collected_at_iso=now_iso,
        )
        self._dossiers[subagent_id] = collected_dossier
        return collected_dossier

    def get_subagent_dossier(self, subagent_id: str) -> EphemeralSubagentDossier | None:
        return self._dossiers.get(subagent_id)

    def get_transient_logs(self, subagent_id: str) -> tuple[str, ...]:
        return tuple(self._transient_logs.get(subagent_id, []))
