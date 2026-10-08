"""Cognitive data models for Dream Cognitive Consolidation and Growth Diary.

[POS]
后台梦境认知重组与智能体成长日记数据模型核心契约。
定义动因分类、认知意图动作、假设演绎推断、具身成长日记实体与空间治理报告。

[INPUT]
- 跨会话碎片事实与溯源锚点
- 假设推演论据与演进主题

[OUTPUT]
- DreamMotiveType: 梦境触发动因枚举
- DreamCognitiveActionType: 认知意图动作枚举
- HypotheticalDeduction: 假设演绎推断模型
- DreamCognitiveAction: 认知动作指令实体
- GrowthDiaryEntry: 具备白盒具身心智的人类可读成长日记条目
- CognitiveConsolidationReport: 梦境认知重组端到端综合报告
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from myrm_agent_harness.toolkits.memory.dreaming.provenance import (
    MemoryProvenanceAnchor,
)


class DreamMotiveType(StrEnum):
    """Taxonomy of triggers driving cognitive dream consolidation."""

    NEWNESS = "newness"
    FREQUENCY = "frequency"
    CONFLICT = "conflict"
    FEEDBACK = "feedback"
    FRAGMENTATION = "fragmentation"


class DreamTargetMemoryType(StrEnum):
    """Target memory store classification for cognitive mutations."""

    PROFILE = "profile"
    SKILL = "skill"
    RULE = "rule"
    INSIGHT = "insight"
    ARCHIVE = "archive"


class DreamCognitiveActionType(StrEnum):
    """Mutation intent emitted by cognitive dream reflection."""

    CREATE = "create"
    UPDATE = "update"
    MERGE = "merge"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class HypotheticalDeduction:
    """Hypothetical-deduction justification verifying cognitive value.

    Validates that a concrete query can be handled significantly better
    with the consolidated higher-level insight present.
    """

    hypothetical_query: str
    improved_response_reasoning: str
    confidence_gain: float = 0.25

    def to_dict(self) -> dict[str, object]:
        return {
            "hypothetical_query": self.hypothetical_query,
            "improved_response_reasoning": self.improved_response_reasoning,
            "confidence_gain": self.confidence_gain,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> HypotheticalDeduction:
        return cls(
            hypothetical_query=str(data.get("hypothetical_query", "")),
            improved_response_reasoning=str(data.get("improved_response_reasoning", "")),
            confidence_gain=float(data.get("confidence_gain", 0.25)),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class DreamCognitiveAction:
    """A single memory mutation emitted by cognitive dreaming."""

    action_id: str
    action_type: DreamCognitiveActionType
    target_type: DreamTargetMemoryType
    target_id: str | None
    source_fact_ids: list[str]
    payload_statement: str
    deduction: HypotheticalDeduction
    confidence: float
    cube_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "target_type": self.target_type.value,
            "target_id": self.target_id,
            "source_fact_ids": list(self.source_fact_ids),
            "payload_statement": self.payload_statement,
            "deduction": self.deduction.to_dict(),
            "confidence": self.confidence,
            "cube_id": self.cube_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> DreamCognitiveAction:
        raw_act_type = str(data.get("action_type", "create"))
        act_type = (
            DreamCognitiveActionType(raw_act_type)
            if raw_act_type in DreamCognitiveActionType._value2member_map_
            else DreamCognitiveActionType.CREATE
        )
        raw_tgt_type = str(data.get("target_type", "insight"))
        tgt_type = (
            DreamTargetMemoryType(raw_tgt_type)
            if raw_tgt_type in DreamTargetMemoryType._value2member_map_
            else DreamTargetMemoryType.INSIGHT
        )
        raw_deduction = data.get("deduction")
        deduction = (
            HypotheticalDeduction.from_dict(raw_deduction)
            if isinstance(raw_deduction, Mapping)
            else HypotheticalDeduction(hypothetical_query="", improved_response_reasoning="")
        )
        raw_sources = data.get("source_fact_ids")
        sources = [str(s) for s in raw_sources] if isinstance(raw_sources, list) else []

        raw_cube = data.get("cube_id")
        cube_str = str(raw_cube) if raw_cube is not None else None
        raw_target = data.get("target_id")
        target_str = str(raw_target) if raw_target is not None else None

        return cls(
            action_id=str(data.get("action_id", f"act_{uuid.uuid4().hex[:8]}")),
            action_type=act_type,
            target_type=tgt_type,
            target_id=target_str,
            source_fact_ids=sources,
            payload_statement=str(data.get("payload_statement", "")),
            deduction=deduction,
            confidence=float(data.get("confidence", 0.8)),  # type: ignore[arg-type]
            cube_id=cube_str,
        )


@dataclass(frozen=True)
class DreamMotive:
    """A concrete stimulus triggering a cognitive consolidation cluster."""

    motive_id: str
    motive_type: DreamMotiveType
    description: str
    candidate_fact_ids: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "motive_id": self.motive_id,
            "motive_type": self.motive_type.value,
            "description": self.description,
            "candidate_fact_ids": list(self.candidate_fact_ids),
        }


@dataclass(frozen=True)
class DreamCognitiveCluster:
    """A semantic cluster grouped by an underlying cognitive motive."""

    cluster_id: str
    motive: DreamMotive
    fact_contents: list[str]
    topic_tags: list[str]
    provenance_anchors: list[MemoryProvenanceAnchor] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "motive": self.motive.to_dict(),
            "fact_contents": list(self.fact_contents),
            "topic_tags": list(self.topic_tags),
            "provenance_anchors": [a.to_dict() for a in self.provenance_anchors],
        }


@dataclass
class GrowthDiaryEntry:
    """Human-readable embodiment journal entry of the AI's mind evolution."""

    diary_id: str
    title: str
    summary: str
    reflective_narrative: str
    motive_type: DreamMotiveType
    themes: list[str]
    cube_id: str | None
    generated_actions: list[DreamCognitiveAction]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def format_markdown(self) -> str:
        """Render a beautiful, human-readable markdown presentation."""
        dt_str = self.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = [
            f"# 📔 智能体心智演进日记: {self.title}",
            f"> **记录时间**: `{dt_str}` | **动因**: `{self.motive_type.value}` | **归档空间**: `{self.cube_id or '全局共享'}`",
            "",
            "### 💡 核心洞察摘要",
            self.summary,
            "",
            "### 🧠 具身心智自省 (Reflective Narrative)",
            self.reflective_narrative,
            "",
            "### 🏷️ 演进主题标签",
            ", ".join(f"`#{t}`" for t in self.themes) if self.themes else "_无特定标签_",
            "",
            "### ⚡ 认知突变动作",
        ]
        if not self.generated_actions:
            lines.append("_本次梦境反思维持既有心智结构，未产生破坏性突变动作。_")
        else:
            for act in self.generated_actions:
                lines.append(
                    f"- **[{act.action_type.value.upper()}]** 目标: `{act.target_type.value}` | 信心度: `{act.confidence:.2f}`"
                )
                lines.append(f"  - 认知命题: {act.payload_statement}")
                lines.append(f"  - 假设推演增益: {act.deduction.improved_response_reasoning}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "diary_id": self.diary_id,
            "title": self.title,
            "summary": self.summary,
            "reflective_narrative": self.reflective_narrative,
            "motive_type": self.motive_type.value,
            "themes": list(self.themes),
            "cube_id": self.cube_id,
            "generated_actions": [a.to_dict() for a in self.generated_actions],
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class CognitiveConsolidationReport:
    """Comprehensive execution report of an end-to-end cognitive dreaming run."""

    run_id: str
    cube_id: str | None
    timestamp: datetime
    duration_ms: float
    input_fact_count: int
    clusters_formed: int
    actions_generated: int
    diary_entries: list[GrowthDiaryEntry]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "cube_id": self.cube_id,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "input_fact_count": self.input_fact_count,
            "clusters_formed": self.clusters_formed,
            "actions_generated": self.actions_generated,
            "diary_entries": [d.to_dict() for d in self.diary_entries],
        }
