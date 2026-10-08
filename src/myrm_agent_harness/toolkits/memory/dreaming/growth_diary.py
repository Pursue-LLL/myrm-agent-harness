"""Growth diary generation engine for AI embodied self-reflection.

[POS]
白盒智能体成长日记生成引擎。将梦境反思中的认知动作、聚类动机与双向溯源锚点，
转化为人类可读、具身心智演进感的结构化成长日记实体。

[INPUT]
- DreamCognitiveCluster: 聚类动因与关联事实
- list[DreamCognitiveAction]: 本次反思生成的突变动作
- cube_id: 归属的空间治理立方体

[OUTPUT]
- GrowthDiaryGenerator: 具身自省日记生成器
- GrowthDiaryEntry: 结构化与美化排版的日记条目
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.dreaming.cognitive_models import (
    DreamCognitiveAction,
    DreamCognitiveCluster,
    GrowthDiaryEntry,
)

_THEME_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "user", "agent",
    "will", "should", "always", "strictly", "prefer", "mandate", "when",
    "必须", "应该", "严禁", "优先", "用户", "项目", "配置", "规范",
}
_TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class GrowthDiaryGenerator:
    """Transforms raw cognitive clustering and actions into human-readable growth diaries."""

    @classmethod
    def extract_themes(cls, texts: list[str], max_themes: int = 5) -> list[str]:
        """Extract dominant topic keywords as mind evolution tags."""
        freq: dict[str, int] = {}
        for text in texts:
            tokens = _TOKEN_PATTERN.findall(text)
            for tok in tokens:
                low = tok.lower()
                if len(low) > 1 and low not in _THEME_STOPWORDS:
                    freq[low] = freq.get(low, 0) + 1

        sorted_tokens = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)
        return [tok for tok, _ in sorted_tokens[:max_themes]]

    @classmethod
    def generate_narrative(
        cls,
        cluster: DreamCognitiveCluster,
        actions: list[DreamCognitiveAction],
    ) -> tuple[str, str]:
        """Synthesize human-readable title and reflective narrative from cluster actions."""
        motive_type = cluster.motive.motive_type
        motive_desc = cluster.motive.description

        if actions:
            top_action = actions[0]
            title = f"认知演进: 针对 [{top_action.target_type.value}] 的心智模型固化"
            narrative = (
                f"在最近的会话交互中，检测到动因 [{motive_type.value}]（{motive_desc}）。"
                f"经过跨会话关联反思，AI 确认了一项高阶认知准则：\"{top_action.payload_statement}\"。"
                f"该洞察通过了假设演绎推断检验：{top_action.deduction.improved_response_reasoning}。"
                f"该心智演进不仅提升了交互置信度（+{top_action.deduction.confidence_gain:.2f}），"
                "而且将持续指引未来同类复杂工程任务的决策精度。"
            )
        else:
            title = f"周期自省: 动因 [{motive_type.value}] 稳态检视"
            narrative = (
                f"针对动因 [{motive_type.value}]（{motive_desc}）进行了跨会话事实比对。"
                "当前既有心智规则与经验库保持高度稳健一致，未触发额外规则合并或修正操作。"
            )

        summary = f"捕获到 {len(cluster.fact_contents)} 条相关事实碎片，提炼并验证了 {len(actions)} 项心智突变动作。"
        return title, summary, narrative

    def create_entry(
        self,
        cluster: DreamCognitiveCluster,
        actions: list[DreamCognitiveAction],
        cube_id: str | None = None,
    ) -> GrowthDiaryEntry:
        """Construct a complete, well-formed GrowthDiaryEntry."""
        title, summary, narrative = self.generate_narrative(cluster, actions)
        all_text = [cluster.motive.description] + cluster.fact_contents + [a.payload_statement for a in actions]
        themes = self.extract_themes(all_text)

        diary_id = f"diary_{uuid.uuid4().hex[:10]}"
        return GrowthDiaryEntry(
            diary_id=diary_id,
            title=title,
            summary=summary,
            reflective_narrative=narrative,
            motive_type=cluster.motive.motive_type,
            themes=themes,
            cube_id=cube_id,
            generated_actions=list(actions),
            created_at=datetime.now(UTC),
        )
