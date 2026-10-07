# ============================================================================
# # SelfDismantlingCuratorEngine - Memory & Skill Distillation Engine (Item 149)
# # Automatically evaluates, distills, and prunes stale/redundant memories & skills
# # guided by transparent, user-customizable curation rules.
# ============================================================================

from __future__ import annotations

import time

from .anti_sycophancy_types import (
    CuratedAction,
    CuratedItemVerdict,
    CuratorCustomRules,
    CuratorDismantlingReport,
    CuratorEvaluationMetric,
)


class SelfDismantlingCuratorEngine:
    """Performs self-distillation sweeps over memory and skill artifacts."""

    def __init__(self, default_rules: CuratorCustomRules | None = None) -> None:
        self.default_rules = default_rules or CuratorCustomRules()

    def calculate_text_similarity(self, text_a: str, text_b: str) -> float:
        """Calculates token-level Dice coefficient similarity between two text snippets."""
        tokens_a = set(text_a.lower().split())
        tokens_b = set(text_b.lower().split())
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = len(tokens_a & tokens_b)
        total_tokens = len(tokens_a) + len(tokens_b)
        return float(2.0 * intersection / total_tokens) if total_tokens > 0 else 0.0

    def evaluate_item(
        self,
        item: dict[str, str | float | int | bool],
        existing_contents: list[str],
        rules: CuratorCustomRules,
    ) -> tuple[CuratedAction, str, CuratorEvaluationMetric, str | None]:
        """Evaluates an individual artifact and returns its curation verdict."""
        content = str(item.get("content", ""))
        created_at = float(item.get("created_at", time.time()))

        # 1. Staleness assessment
        age_days = max(0.0, (time.time() - created_at) / 86400.0)
        staleness = min(1.0, age_days / float(rules.max_staleness_days))

        # 2. Redundancy assessment
        max_similarity = 0.0
        for prior in existing_contents:
            sim = self.calculate_text_similarity(content, prior)
            if sim > max_similarity:
                max_similarity = sim
        redundancy = max_similarity

        # 3. Relevance assessment
        relevance = 0.8
        for guideline in rules.user_guidelines:
            if any(term in content.lower() for term in guideline.lower().split()):
                relevance = min(1.0, relevance + 0.1)

        # 4. Overall composite health
        overall_health = relevance * (1.0 - redundancy * 0.4) * (1.0 - staleness * 0.5)

        metric = CuratorEvaluationMetric(
            relevance_score=round(relevance, 3),
            staleness_score=round(staleness, 3),
            redundancy_score=round(redundancy, 3),
            overall_health=round(overall_health, 3),
        )

        # 5. Determine action
        if overall_health < rules.prune_threshold or staleness >= 0.95:
            return CuratedAction.PRUNE, f"健康分低于阈值 ({overall_health:.2f} < {rules.prune_threshold}) 或已过时", metric, None

        if redundancy >= rules.dedup_similarity_threshold:
            # Distill redundant item into concise bullet
            distilled = f"• [提纯核心] {content[:80].strip()}..."
            return CuratedAction.DISTILL, f"与已有条目相似度过高 ({redundancy:.2f})，自动执行要点蒸馏", metric, distilled

        return CuratedAction.RETAIN, "活跃且具有独特价值，予以保留", metric, None

    def curate_knowledge_and_skills(
        self,
        items: list[dict[str, str | float | int | bool]],
        custom_rules: CuratorCustomRules | None = None,
    ) -> CuratorDismantlingReport:
        """Executes a curation sweep over provided memory/skill artifacts."""
        rules = custom_rules or self.default_rules
        verdicts: list[CuratedItemVerdict] = []
        observed_contents: list[str] = []

        pruned_count = 0
        distilled_count = 0
        retained_count = 0

        for item in items:
            item_id = str(item.get("id", f"item-{len(verdicts) + 1}"))
            item_type = str(item.get("type", "memory"))
            content = str(item.get("content", ""))

            action, reason, metric, distilled_content = self.evaluate_item(
                item=item,
                existing_contents=observed_contents,
                rules=rules,
            )

            if action == CuratedAction.PRUNE:
                pruned_count += 1
            elif action == CuratedAction.DISTILL:
                distilled_count += 1
                observed_contents.append(content)
            else:
                retained_count += 1
                observed_contents.append(content)

            verdicts.append(
                CuratedItemVerdict(
                    item_id=item_id,
                    item_type=item_type,
                    action=action,
                    reason=reason,
                    metric=metric,
                    distilled_content=distilled_content,
                )
            )

        # Generate summary markdown
        md_lines = [
            "# 🧹 Hermes Curator 自我蒸馏策展报告",
            f"- **扫描总条目数**：{len(items)} 项",
            f"- **已淘汰清理 (Pruned)**：{pruned_count} 项",
            f"- **已提纯精简 (Distilled)**：{distilled_count} 项",
            f"- **健康保留 (Retained)**：{retained_count} 项",
            "\n### 策展准则白盒透视：",
        ]
        if rules.user_guidelines:
            for g in rules.user_guidelines:
                md_lines.append(f"- 规则: {g}")
        else:
            md_lines.append("- 使用默认工业级高保真自净化准则")

        summary_md = "\n".join(md_lines)

        return CuratorDismantlingReport(
            scanned_items_count=len(items),
            pruned_count=pruned_count,
            distilled_count=distilled_count,
            retained_count=retained_count,
            verdicts=verdicts,
            summary_markdown=summary_md,
            executed_at=time.time(),
        )
