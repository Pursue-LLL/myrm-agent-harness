"""Core pipeline orchestrating Dream Cognitive Consolidation and Higher-Level Insight deduction.

[POS]
后台梦境认知重组管道核心引擎。管理跨会话碎片到高阶认知洞察的演进闭环：
动因聚类识别 ➔ 假设演绎推断 ➔ 记忆突变动作生成 ➔ 具身成长日记归档。

[INPUT]
- fragments: 跨会话会话记忆碎片
- cube_id: 目标挂载的 Memory Cube 作用域
- target_project_id: 项目隔离范围

[OUTPUT]
- DreamCognitivePipeline: 跨会话高阶认知重组执行管道
- CognitiveConsolidationReport: 包含高阶动作与具身演进日记的最终报告
"""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.dreaming.cognitive_models import (
    CognitiveConsolidationReport,
    DreamCognitiveAction,
    DreamCognitiveActionType,
    DreamCognitiveCluster,
    DreamMotive,
    DreamMotiveType,
    DreamTargetMemoryType,
    GrowthDiaryEntry,
    HypotheticalDeduction,
)
from myrm_agent_harness.toolkits.memory.dreaming.growth_diary import (
    GrowthDiaryGenerator,
)
from myrm_agent_harness.toolkits.memory.dreaming.models import (
    DreamSessionFragment,
)
from myrm_agent_harness.toolkits.memory.dreaming.provenance import (
    MemoryProvenanceAnchor,
    ProjectScopeIsolationGuard,
    SensitiveProvenanceGuard,
)

_TOKEN_REGEX = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class DreamCognitivePipeline:
    """Orchestrates idle multi-session cognitive consolidation into higher-level insights."""

    def __init__(
        self,
        diary_generator: GrowthDiaryGenerator | None = None,
        min_frequency_threshold: int = 2,
    ) -> None:
        self._diary_generator = diary_generator or GrowthDiaryGenerator()
        self._min_frequency_threshold = min_frequency_threshold

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        return {tok.lower() for tok in _TOKEN_REGEX.findall(text) if len(tok) > 1}

    def _cluster_by_motives(
        self,
        fragments: Sequence[DreamSessionFragment],
        target_project_id: str | None,
    ) -> list[DreamCognitiveCluster]:
        """Group cross-session memory statements into clusters based on cognitive motives."""
        token_to_facts: dict[str, list[tuple[str, str, MemoryProvenanceAnchor | None]]] = defaultdict(list)
        all_raw_facts: list[tuple[str, str, MemoryProvenanceAnchor | None]] = []

        for frag in fragments:
            if not ProjectScopeIsolationGuard.validate_scope(frag.project_id, target_project_id):
                continue

            for mem in frag.memories:
                content = str(mem.get("content", "")).strip()
                if not content or SensitiveProvenanceGuard.contains_sensitive_content(content):
                    continue

                fact_id = str(mem.get("id") or mem.get("fact_id") or f"fact_{frag.session_id}_{uuid.uuid4().hex[:6]}")
                # Extract first anchor if available
                anchor: MemoryProvenanceAnchor | None = None
                evidences = mem.get("evidence")
                if isinstance(evidences, list) and evidences:
                    first_ev = evidences[0]
                    if isinstance(first_ev, dict):
                        quote = str(first_ev.get("quote_snippet") or first_ev.get("verbatim_quote") or "")
                        if quote and not SensitiveProvenanceGuard.contains_sensitive_content(quote):
                            anchor = MemoryProvenanceAnchor(
                                session_id=frag.session_id,
                                message_id=str(first_ev.get("message_id") or f"msg_{frag.session_id}"),
                                speaker=str(first_ev.get("speaker") or "user"),
                                timestamp=frag.extracted_at,
                                verbatim_quote=quote,
                                project_id=frag.project_id,
                            )

                all_raw_facts.append((fact_id, content, anchor))
                tokens = self._tokenize(content)
                for tok in tokens:
                    token_to_facts[tok].append((fact_id, content, anchor))

        clusters: list[DreamCognitiveCluster] = []
        processed_fact_ids: set[str] = set()

        # 1. Frequency Motive: tokens appearing across multiple distinct facts
        for token, fact_tuples in sorted(token_to_facts.items(), key=lambda kv: len(kv[1]), reverse=True):
            if len(fact_tuples) >= self._min_frequency_threshold:
                unprocessed = [t for t in fact_tuples if t[0] not in processed_fact_ids]
                if len(unprocessed) >= self._min_frequency_threshold:
                    cluster_fact_ids = [t[0] for t in unprocessed]
                    cluster_contents = [t[1] for t in unprocessed]
                    cluster_anchors = [t[2] for t in unprocessed if t[2] is not None]
                    processed_fact_ids.update(cluster_fact_ids)

                    motive = DreamMotive(
                        motive_id=f"mot_{uuid.uuid4().hex[:8]}",
                        motive_type=DreamMotiveType.FREQUENCY,
                        description=f"在多次会话中重复出现的关键共性模式: '{token}'",
                        candidate_fact_ids=cluster_fact_ids,
                    )
                    clusters.append(
                        DreamCognitiveCluster(
                            cluster_id=f"clus_{uuid.uuid4().hex[:8]}",
                            motive=motive,
                            fact_contents=cluster_contents,
                            topic_tags=[token],
                            provenance_anchors=cluster_anchors,
                        )
                    )

        # 2. Newness Motive: remaining novel facts grouped into high-value fresh insights
        remaining_facts = [t for t in all_raw_facts if t[0] not in processed_fact_ids]
        if remaining_facts:
            batch_fact_ids = [t[0] for t in remaining_facts]
            batch_contents = [t[1] for t in remaining_facts]
            batch_anchors = [t[2] for t in remaining_facts if t[2] is not None]
            motive = DreamMotive(
                motive_id=f"mot_{uuid.uuid4().hex[:8]}",
                motive_type=DreamMotiveType.NEWNESS,
                description="最近会话中新捕获到的独立事实与特定规则",
                candidate_fact_ids=batch_fact_ids,
            )
            clusters.append(
                DreamCognitiveCluster(
                    cluster_id=f"clus_{uuid.uuid4().hex[:8]}",
                    motive=motive,
                    fact_contents=batch_contents,
                    topic_tags=["novelty", "recent"],
                    provenance_anchors=batch_anchors,
                )
            )

        return clusters

    def _synthesize_actions(
        self,
        cluster: DreamCognitiveCluster,
        cube_id: str | None,
    ) -> list[DreamCognitiveAction]:
        """Formulate hypothetical deductions and actionable memory mutations for a cluster."""
        actions: list[DreamCognitiveAction] = []
        motive_type = cluster.motive.motive_type

        if motive_type == DreamMotiveType.FREQUENCY:
            # Frequency represents a solidified user rule or engineering habit
            topic = cluster.topic_tags[0] if cluster.topic_tags else "general"
            common_snippet = "；".join(cluster.fact_contents[:3])
            payload_statement = f"跨会话固化认知: 用户在涉及 [{topic}] 相关任务时具有明确偏好与强约束（{common_snippet}）。"

            hypothetical = HypotheticalDeduction(
                hypothetical_query=f"在未来遇到与 '{topic}' 相关的设计或实现选择时应采取何种策略？",
                improved_response_reasoning="无需再次反复询问用户，直接依据已验证的高频认知习惯执行，缩短决策延时并保持一致性。",
                confidence_gain=0.35,
            )
            action = DreamCognitiveAction(
                action_id=f"act_{uuid.uuid4().hex[:8]}",
                action_type=DreamCognitiveActionType.MERGE,
                target_type=DreamTargetMemoryType.RULE,
                target_id=None,
                source_fact_ids=list(cluster.motive.candidate_fact_ids),
                payload_statement=payload_statement,
                deduction=hypothetical,
                confidence=0.92,
                cube_id=cube_id,
            )
            actions.append(action)

        elif motive_type == DreamMotiveType.NEWNESS:
            # New facts turn into candidate insight/skill memory
            for idx, fact_text in enumerate(cluster.fact_contents[:2]):
                payload_statement = f"提炼新知: {fact_text}"
                hypothetical = HypotheticalDeduction(
                    hypothetical_query="何时需要运用此新事实？",
                    improved_response_reasoning="在遇到相关领域任务时优先作为上下文参考召回。",
                    confidence_gain=0.20,
                )
                action = DreamCognitiveAction(
                    action_id=f"act_{uuid.uuid4().hex[:8]}",
                    action_type=DreamCognitiveActionType.CREATE,
                    target_type=DreamTargetMemoryType.INSIGHT,
                    target_id=None,
                    source_fact_ids=[cluster.motive.candidate_fact_ids[idx]],
                    payload_statement=payload_statement,
                    deduction=hypothetical,
                    confidence=0.85,
                    cube_id=cube_id,
                )
                actions.append(action)

        return actions

    def consolidate(
        self,
        fragments: Sequence[DreamSessionFragment],
        cube_id: str | None = None,
        target_project_id: str | None = None,
    ) -> CognitiveConsolidationReport:
        """Run complete cognitive consolidation cycle across fragments."""
        start_time = time.perf_counter()
        run_id = f"cog_dream_{uuid.uuid4().hex[:8]}"

        clusters = self._cluster_by_motives(fragments, target_project_id=target_project_id)
        all_actions: list[DreamCognitiveAction] = []
        diaries: list[GrowthDiaryEntry] = []

        total_input_facts = sum(len(f.memories) for f in fragments)

        for clus in clusters:
            actions = self._synthesize_actions(clus, cube_id=cube_id)
            all_actions.extend(actions)
            diary_entry = self._diary_generator.create_entry(clus, actions, cube_id=cube_id)
            diaries.append(diary_entry)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return CognitiveConsolidationReport(
            run_id=run_id,
            cube_id=cube_id,
            timestamp=datetime.now(UTC),
            duration_ms=elapsed_ms,
            input_fact_count=total_input_facts,
            clusters_formed=len(clusters),
            actions_generated=len(all_actions),
            diary_entries=diaries,
        )
