# [POS] myrm_agent_harness/agent/context_management/project_state/context_projection_engine.py
# [INPUT] ProjectionQuery, ProjectedContextSlice, LivingFact, ProjectFactType, ProjectStateLivingFactLedger
# [OUTPUT] FourTierContextProjectionEngine

"""面向长期项目的四层级联动态上下文投影流水线引擎。"""

from __future__ import annotations

import re

from .living_fact_ledger import ProjectStateLivingFactLedger
from .types import (
    LivingFact,
    ProjectedContextSlice,
    ProjectFactType,
    ProjectionQuery,
)


class FourTierContextProjectionEngine:
    """四层级联上下文投影流水线引擎。

    流水线依次执行：
    1. Tier 1 - Rule Projection: 目标组件直接约束与接口契约投影；
    2. Tier 2 - Dependency Expansion: 关联组件方案与明确被否决的路径展开；
    3. Tier 3 - Semantic Retrieval: 相似任务历史验证成果与知识召回；
    4. Tier 4 - Projection Router: 权重路由排序与 Token 预算安全截断。
    """

    def __init__(self, ledger: ProjectStateLivingFactLedger) -> None:
        self._ledger = ledger

    def project_context(self, query: ProjectionQuery) -> ProjectedContextSlice:
        """执行四层级联投影流水线，萃取当前子任务的高置信度上下文切片。"""
        all_facts = self._ledger.list_facts(query.project_id)
        if not all_facts:
            return ProjectedContextSlice(
                project_id=query.project_id,
                facts=[],
                formatted_prompt_block="",
                total_tokens_estimated=0,
                projected_by_tier={
                    "rule_projection": 0,
                    "dependency_expansion": 0,
                    "semantic_retrieval": 0,
                    "router_selected": 0,
                },
            )

        target_comps = {c.strip().lower() for c in query.target_components if c.strip()}
        tier1_facts: list[LivingFact] = []
        tier2_facts: list[LivingFact] = []
        tier3_facts: list[LivingFact] = []

        seen_ids: set[str] = set()

        # Tier 1: 规则与接口直接投影 (Rule Projection)
        for fact in all_facts:
            f_comps = {c.strip().lower() for c in fact.target_components}
            if (
                target_comps
                and not target_comps.isdisjoint(f_comps)
                and fact.fact_type
                in (
                    ProjectFactType.CONSTRAINT,
                    ProjectFactType.INTERFACE_CONTRACT,
                )
            ):
                tier1_facts.append(fact)
                seen_ids.add(fact.fact_id)

        # Tier 2: 依赖展开与否决项展开 (Dependency & Rejection Expansion)
        for fact in all_facts:
            if fact.fact_id in seen_ids:
                continue
            f_comps = {c.strip().lower() for c in fact.target_components}
            # 关联组件的已决方案，或者全局被否决方案(反模式，绝对不能踩坑)
            if fact.fact_type == ProjectFactType.REJECTED_ALTERNATIVE or (
                target_comps
                and not target_comps.isdisjoint(f_comps)
                and fact.fact_type == ProjectFactType.DECISION
            ):
                tier2_facts.append(fact)
                seen_ids.add(fact.fact_id)

        # Tier 3: 语义检索召回 (Semantic Match for Task)
        query_words = set(re.findall(r"\w+", query.target_task.lower()))
        for fact in all_facts:
            if fact.fact_id in seen_ids:
                continue
            text = f"{fact.title} {fact.content} {fact.reason_or_constraint}".lower()
            fact_words = set(re.findall(r"\w+", text))
            overlap = query_words.intersection(fact_words)
            if len(overlap) >= 2 or (query_words and len(overlap) / len(query_words) >= 0.2):
                tier3_facts.append(fact)
                seen_ids.add(fact.fact_id)

        # Tier 4: 模型决策路由与 Token 预算安全截断 (Projection Router)
        candidate_pool: list[LivingFact] = tier1_facts + tier2_facts + tier3_facts
        # 若仍有全局核心约束未被包含，兜底补全
        for fact in all_facts:
            if fact.fact_id not in seen_ids and fact.fact_type == ProjectFactType.CONSTRAINT:
                candidate_pool.append(fact)
                seen_ids.add(fact.fact_id)

        # 按重要性权重与验证置信度排序
        def fact_priority_score(f: LivingFact) -> float:
            base_weights: dict[ProjectFactType, float] = {
                ProjectFactType.CONSTRAINT: 50.0,
                ProjectFactType.REJECTED_ALTERNATIVE: 40.0,
                ProjectFactType.INTERFACE_CONTRACT: 35.0,
                ProjectFactType.DECISION: 30.0,
                ProjectFactType.VALIDATION_RESULT: 20.0,
            }
            weight = base_weights.get(f.fact_type, 10.0)
            confidence = (f.validation_count * 2.0) - (f.regression_count * 3.0)
            return weight + confidence

        candidate_pool.sort(key=fact_priority_score, reverse=True)

        selected_facts: list[LivingFact] = []
        accumulated_chars = 0
        char_budget = query.token_budget * 4  # 估算 1 token ≈ 4 字符

        for fact in candidate_pool:
            item_chars = len(fact.title) + len(fact.content) + len(fact.reason_or_constraint) + 60
            if accumulated_chars + item_chars > char_budget and selected_facts:
                break
            selected_facts.append(fact)
            accumulated_chars += item_chars

        # 格式化组装提示词块
        formatted_block = self._format_prompt_block(selected_facts)
        total_tokens = max(1, len(formatted_block) // 4)

        return ProjectedContextSlice(
            project_id=query.project_id,
            facts=selected_facts,
            formatted_prompt_block=formatted_block,
            total_tokens_estimated=total_tokens,
            projected_by_tier={
                "rule_projection": len(tier1_facts),
                "dependency_expansion": len(tier2_facts),
                "semantic_retrieval": len(tier3_facts),
                "router_selected": len(selected_facts),
            },
        )

    def _format_prompt_block(self, facts: list[LivingFact]) -> str:
        """结构化渲染 Project State 提示词块。"""
        if not facts:
            return ""

        constraints = [f for f in facts if f.fact_type == ProjectFactType.CONSTRAINT]
        decisions = [
            f for f in facts if f.fact_type in (ProjectFactType.DECISION, ProjectFactType.INTERFACE_CONTRACT)
        ]
        rejections = [f for f in facts if f.fact_type == ProjectFactType.REJECTED_ALTERNATIVE]
        others = [f for f in facts if f not in constraints and f not in decisions and f not in rejections]

        lines: list[str] = [
            "<project_state_context>",
            "<!-- 本上下文由 ProjectState 四层级联投影流水线动态萃取，严禁违反以下既定约束与决策 -->",
        ]

        if constraints:
            lines.append("### 1. 硬性物理边界与规则约束 [CONSTRAINTS]")
            for c in constraints:
                lines.append(f"- **{c.title}**: {c.content}")
                if c.reason_or_constraint:
                    lines.append(f"  *约束理由*: {c.reason_or_constraint}")

        if decisions:
            lines.append("### 2. 已确认架构决策与正式接口 [DECISIONS & CONTRACTS]")
            for d in decisions:
                lines.append(f"- **{d.title}** ({d.fact_type.value}): {d.content}")

        if rejections:
            lines.append("### 3. 已否决方案与反模式警示 [REJECTED ALTERNATIVES - DO NOT RETRY]")
            for r in rejections:
                lines.append(f"- ⛔ **{r.title}**: {r.content}")
                if r.reason_or_constraint:
                    lines.append(f"  *否决原因*: {r.reason_or_constraint}")

        if others:
            lines.append("### 4. 经验沉淀与验证记录 [VALIDATED EXPERIENCES]")
            for o in others:
                lines.append(
                    f"- **{o.title}** (验证通过 {o.validation_count} 次, 阶段 {o.promotion_stage.value}): {o.content}"
                )

        lines.append("</project_state_context>")
        return "\n".join(lines)
