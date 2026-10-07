# [POS] myrm_agent_harness/agent/context_management/project_state/living_fact_ledger.py
# [INPUT] LivingFact, ProjectFactType, FactPromotionStage
# [OUTPUT] ProjectStateLivingFactLedger

"""长期项目动态事实状态账本管理器，统一纳管已决议方案、被否决路径与硬性物理约束。"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from .types import FactPromotionStage, LivingFact, ProjectFactType


class ProjectStateLivingFactLedger:
    """长期项目动态事实状态账本核心管理器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # project_id -> {fact_id -> LivingFact}
        self._store: dict[str, dict[str, LivingFact]] = {}

    def record_fact(self, fact: LivingFact) -> LivingFact:
        """记录或更新一条动态事实项。"""
        with self._lock:
            if fact.project_id not in self._store:
                self._store[fact.project_id] = {}
            self._store[fact.project_id][fact.fact_id] = fact
            return fact

    def get_fact(self, project_id: str, fact_id: str) -> LivingFact | None:
        """获取指定项目下的单个事实项。"""
        with self._lock:
            project_facts = self._store.get(project_id)
            if not project_facts:
                return None
            return project_facts.get(fact_id)

    def list_facts(
        self,
        project_id: str,
        fact_type: ProjectFactType | None = None,
        stage: FactPromotionStage | None = None,
    ) -> list[LivingFact]:
        """按类型或晋升阶段过滤指定项目下的事实列表。"""
        with self._lock:
            project_facts = self._store.get(project_id, {})
            facts = list(project_facts.values())

        filtered: list[LivingFact] = []
        for f in facts:
            if fact_type is not None and f.fact_type != fact_type:
                continue
            if stage is not None and f.promotion_stage != stage:
                continue
            filtered.append(f)
        return filtered

    def find_by_components(
        self,
        project_id: str,
        components: list[str],
    ) -> list[LivingFact]:
        """检索与指定目标组件或关联路径匹配的所有事实项。"""
        target_set = {c.strip().lower() for c in components if c.strip()}
        if not target_set:
            return []

        all_facts = self.list_facts(project_id)
        matched: list[LivingFact] = []
        for fact in all_facts:
            fact_components = {c.strip().lower() for c in fact.target_components}
            if not target_set.isdisjoint(fact_components):
                matched.append(fact)
        return matched

    def remove_fact(self, project_id: str, fact_id: str) -> bool:
        """从账本中移除指定事实项。"""
        with self._lock:
            project_facts = self._store.get(project_id)
            if not project_facts or fact_id not in project_facts:
                return False
            del project_facts[fact_id]
            return True

    def clear_project(self, project_id: str) -> None:
        """清空指定项目的事实账本。"""
        with self._lock:
            if project_id in self._store:
                del self._store[project_id]

    def create_fact(
        self,
        project_id: str,
        fact_id: str,
        fact_type: ProjectFactType,
        title: str,
        content: str,
        target_components: list[str] | None = None,
        reason_or_constraint: str = "",
        stage: FactPromotionStage = FactPromotionStage.CONFIRMED_FACT,
        metadata: dict[str, str] | None = None,
    ) -> LivingFact:
        """便捷构造并登记一条新事实。"""
        now = datetime.now(UTC).isoformat()
        fact = LivingFact(
            fact_id=fact_id,
            project_id=project_id,
            fact_type=fact_type,
            title=title,
            content=content,
            target_components=target_components or [],
            reason_or_constraint=reason_or_constraint,
            promotion_stage=stage,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        return self.record_fact(fact)
