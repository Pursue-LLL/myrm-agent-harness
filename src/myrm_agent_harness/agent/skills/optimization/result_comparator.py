"""Result Comparator Protocol & Default Implementation

Harness层的结果比对机制。遵循 Mechanism vs Strategy 架构原则：
- Harness层提供 Protocol + StructuredComparator（纯本地机制）
- Server层可实现 SemanticComparator（LLM语义策略）

[OUTPUT]
- ResultComparator: 比对协议接口
- ComparisonDetail: 比对结果数据类
- StructuredComparator: 默认实现（deepdiff + token相似度）

[POS]
Shadow test result comparator. Provides accurate result comparison for the observation feedback loop.

"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class ComparisonDetail:
    """比对结果

    Attributes:
        similarity_score: 综合相似度 (0.0=完全不同, 1.0=完全一致)
        is_match: 是否判定为"一致"（基于 match_threshold）
        structural_score: 结构化字段相似度 (0-1)
        textual_score: 文本内容相似度 (0-1)
        diff_summary: 人类可读的差异摘要
        field_diffs: 各字段的具体差异 {字段路径: (baseline值, candidate值)}
    """

    similarity_score: float
    is_match: bool
    structural_score: float = 1.0
    textual_score: float = 1.0
    diff_summary: str = ""
    field_diffs: dict[str, tuple[str, str]] = field(default_factory=dict)


@runtime_checkable
class ResultComparator(Protocol):
    """结果比对协议

    Harness层定义接口，支持多种实现：
    - StructuredComparator: 默认（deepdiff + token相似度，零LLM成本）
    - SemanticComparator: Server层实现（按需调用LLM语义判定）
    """

    async def compare(self, baseline: dict, candidate: dict) -> ComparisonDetail:
        """比对 baseline 和 candidate 的执行结果

        Args:
            baseline: 基线版本执行结果
            candidate: 候选版本执行结果

        Returns:
            ComparisonDetail 包含相似度分数和差异详情
        """
        ...


class StructuredComparator:
    """默认结构化比对器（零LLM成本）

    两层比对策略：
    Layer 1: JSON 结构化深度对比（字段级 diff）
    Layer 2: 文本内容 token 相似度（Jaccard 系数）
    综合两层结果计算 similarity_score。
    """

    def __init__(self, match_threshold: float = 0.85, structural_weight: float = 0.4, textual_weight: float = 0.6):
        self.match_threshold = match_threshold
        self.structural_weight = structural_weight
        self.textual_weight = textual_weight

    async def compare(self, baseline: dict, candidate: dict) -> ComparisonDetail:
        if not baseline and not candidate:
            return ComparisonDetail(similarity_score=1.0, is_match=True)

        if not baseline or not candidate:
            return ComparisonDetail(
                similarity_score=0.0,
                is_match=False,
                structural_score=0.0,
                textual_score=0.0,
                diff_summary="One side is empty",
            )

        structural_score, field_diffs = self._structural_compare(baseline, candidate)
        textual_score = self._textual_compare(baseline, candidate)

        similarity = self.structural_weight * structural_score + self.textual_weight * textual_score
        similarity = max(0.0, min(1.0, similarity))

        diff_summary = self._build_diff_summary(field_diffs, structural_score, textual_score)

        return ComparisonDetail(
            similarity_score=similarity,
            is_match=similarity >= self.match_threshold,
            structural_score=structural_score,
            textual_score=textual_score,
            diff_summary=diff_summary,
            field_diffs=field_diffs,
        )

    def _structural_compare(self, baseline: dict, candidate: dict) -> tuple[float, dict[str, tuple[str, str]]]:
        """Layer 1: 结构化字段深度对比"""
        field_diffs: dict[str, tuple[str, str]] = {}
        all_keys = set(baseline.keys()) | set(candidate.keys())

        if not all_keys:
            return 1.0, {}

        matching_fields = 0
        for key in all_keys:
            b_val = baseline.get(key)
            c_val = candidate.get(key)

            if b_val == c_val:
                matching_fields += 1
            else:
                b_str = str(b_val)[:200] if b_val is not None else "<missing>"
                c_str = str(c_val)[:200] if c_val is not None else "<missing>"
                field_diffs[key] = (b_str, c_str)

                if isinstance(b_val, dict) and isinstance(c_val, dict):
                    nested_score, _ = self._structural_compare(b_val, c_val)
                    if nested_score > 0.5:
                        matching_fields += nested_score

        return matching_fields / len(all_keys), field_diffs

    def _textual_compare(self, baseline: dict, candidate: dict) -> float:
        """Layer 2: 文本内容 token 相似度（Jaccard 系数）"""
        b_text = self._extract_text(baseline)
        c_text = self._extract_text(candidate)

        if not b_text and not c_text:
            return 1.0
        if not b_text or not c_text:
            return 0.0

        b_tokens = set(self._tokenize(b_text))
        c_tokens = set(self._tokenize(c_text))

        if not b_tokens and not c_tokens:
            return 1.0

        intersection = b_tokens & c_tokens
        union = b_tokens | c_tokens

        return len(intersection) / len(union) if union else 1.0

    def _extract_text(self, data: dict) -> str:
        """递归提取所有文本值"""
        texts: list[str] = []
        for value in data.values():
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, dict):
                texts.append(self._extract_text(value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict):
                        texts.append(self._extract_text(item))
        return " ".join(texts)

    def _tokenize(self, text: str) -> list[str]:
        """简单分词：按空白符和标点切分，转小写"""
        tokens = re.findall(r"\w+", text.lower())
        return tokens

    def _build_diff_summary(
        self, field_diffs: dict[str, tuple[str, str]], structural_score: float, textual_score: float
    ) -> str:
        if not field_diffs:
            return "Results are identical"

        parts = [f"{len(field_diffs)} field(s) differ"]
        changed_fields = list(field_diffs.keys())[:5]
        parts.append(f"Changed: {', '.join(changed_fields)}")
        parts.append(f"Structural: {structural_score:.0%}, Textual: {textual_score:.0%}")

        return "; ".join(parts)
