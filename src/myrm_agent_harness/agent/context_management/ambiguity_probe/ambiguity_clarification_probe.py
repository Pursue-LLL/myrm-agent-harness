"""Core implementation of Ambiguity Clarification Probe and Private Entity Graph Backtracking Engine.

Provides multi-level prompt ambiguity detection, missing constraint inquiry formulation,
private knowledge graph reverse-backtracking, and confirmable outline synthesis.
"""

from __future__ import annotations

import logging
import re
import threading

from .ambiguity_probe_types import (
    AmbiguityLevel,
    BacktrackedContextDossier,
    ClarificationProbeResult,
    ClarificationQuestion,
    EntityGraphMatch,
)

logger = logging.getLogger(__name__)

# Heuristic patterns identifying unspecified pronouns, honorifics, or open-ended artifacts
_HONORIFIC_PATTERN = re.compile(r"([\u4e00-\u9fa5a-zA-Z]{1,2}(?:总监|经理|老板|老师|总|哥|姐))")
_OPEN_ARTIFACT_KEYWORDS: tuple[str, ...] = ("ppt", "方案", "大纲", "报表", "汇报", "总结", "材料", "总结报告")


class AmbiguityClarificationProbe:
    """Pre-flight intent ambiguity analyzer with two-tier clarification and private entity backtracking."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def inspect_prompt(self, prompt: str) -> ClarificationProbeResult:
        """Inspect prompt clarity and identify missing critical constraints or ungrounded entities."""
        with self._lock:
            cleaned = prompt.strip()
            # 1. Detect honorifics or ambiguous entities (e.g., 王总, 李经理)
            detected_entities: list[str] = []
            matches = _HONORIFIC_PATTERN.findall(cleaned)
            for m in matches:
                # Strip leading common functional prepositions/particles
                entity = m
                for prep in ("给", "向", "为", "帮", "对", "跟", "发", "送", "做", "写"):
                    if entity.startswith(prep) and len(entity) > 2:
                        entity = entity[len(prep) :]
                        break
                if entity not in detected_entities:
                    detected_entities.append(entity)

            has_open_artifact = any(kw in cleaned.lower() for kw in _OPEN_ARTIFACT_KEYWORDS)
            char_len = len(cleaned)

            # High ambiguity: very terse prompt (<= 20 chars) with ungrounded entity or open-ended artifact
            if char_len <= 20 and (detected_entities or has_open_artifact):
                questions = (
                    ClarificationQuestion(
                        dimension="target_audience",
                        question="此项任务的主要受众是谁？有何特定的职级或业务关注点？",
                        default_options=("管理层高管", "外部客户/合作方", "内部技术团队"),
                    ),
                    ClarificationQuestion(
                        dimension="core_proposition",
                        question="核心主张或要解决的关键问题是什么？",
                        default_options=("业务汇报与成果展示", "立项申请与资源争取", "问题复盘与改进建议"),
                    ),
                    ClarificationQuestion(
                        dimension="format_specification",
                        question="有无明确的规格、篇幅或模板格式约束？",
                        default_options=("标准 10-15 页精简汇报", "5 页以内快闪沟通", "详细专业长篇提案"),
                    ),
                )
                return ClarificationProbeResult(
                    level=AmbiguityLevel.HIGHLY_AMBIGUOUS,
                    is_ambiguous=True,
                    detected_entities=tuple(detected_entities),
                    clarification_questions=questions,
                    needs_backtracking=bool(detected_entities),
                    reason=f"Prompt is terse ({char_len} chars) with ungrounded entities or open artifact directives.",
                )

            # Moderate ambiguity: medium length (<= 80 chars) referencing ungrounded entities
            if char_len <= 80 and detected_entities:
                questions = (
                    ClarificationQuestion(
                        dimension="verification_scope",
                        question="请确认具体的交付标准与重点倾向。",
                        default_options=("突出数据量化", "突出战略方向", "突出落地排期"),
                    ),
                )
                return ClarificationProbeResult(
                    level=AmbiguityLevel.MODERATE_AMBIGUOUS,
                    is_ambiguous=True,
                    detected_entities=tuple(detected_entities),
                    clarification_questions=questions,
                    needs_backtracking=True,
                    reason="Prompt contains referenced entities requiring background fact grounding.",
                )

            # Clear prompt
            return ClarificationProbeResult(
                level=AmbiguityLevel.CLEAR,
                is_ambiguous=False,
                detected_entities=tuple(detected_entities),
                clarification_questions=(),
                needs_backtracking=False,
                reason="Prompt contains sufficient contextual clarity.",
            )

    def backtrack_entity_graph(
        self,
        entity_name: str,
        private_knowledge_corpus: tuple[dict[str, str], ...],
    ) -> BacktrackedContextDossier:
        """Search private chat and document corpus to ground entities with concrete historical facts."""
        with self._lock:
            matches: list[EntityGraphMatch] = []
            extracted_facts: list[str] = []

            for doc in private_knowledge_corpus:
                doc_title = doc.get("title", doc.get("source", "untitled"))
                doc_content = doc.get("content", "")

                if entity_name in doc_content:
                    lines = [ln.strip() for ln in doc_content.splitlines() if entity_name in ln]
                    # Score confidence based on co-occurrence and detail
                    score = min(1.0, 0.5 + len(lines) * 0.1)
                    match_record = EntityGraphMatch(
                        entity_name=entity_name,
                        entity_type="stakeholder_profile",
                        source_identifier=doc_title,
                        confidence_score=round(score, 2),
                        key_facts=tuple(lines[:5]),
                    )
                    matches.append(match_record)
                    extracted_facts.extend(lines[:3])

            suggested_outline = self._synthesize_outline(entity_name, extracted_facts)

            return BacktrackedContextDossier(
                target_entity=entity_name,
                matches=tuple(matches),
                synthesized_facts=tuple(extracted_facts),
                suggested_outline=suggested_outline,
            )

    def _synthesize_outline(self, entity_name: str, facts: list[str]) -> str:
        """Synthesize a structured execution outline grounded in backtracked facts."""
        lines = [
            f"[CONFIRMABLE PROPOSED OUTLINE: PREPARED FOR {entity_name}]",
            "1. 背景与受众诉求 (Audience Alignment):",
        ]
        if facts:
            for fact in facts[:3]:
                lines.append(f"   • 结合历史溯源: {fact}")
        else:
            lines.append("   • 基于标准业务汇报结构对齐。")

        lines.extend([
            "2. 核心价值主张与解决方案 (Core Proposition)",
            "3. 核心产品与关键数据支持 (Evidence & Metrics)",
            "4. 实施里程碑与排期计划 (Roadmap & Next Steps)",
            "5. 待用户一键确认生效 (Awaiting User Card Confirmation)",
        ])
        return "\n".join(lines)
