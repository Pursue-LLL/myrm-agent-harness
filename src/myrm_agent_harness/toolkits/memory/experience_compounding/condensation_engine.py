"""Semantic condensation and higher-order Golden Rule synthesis engine.

[POS]
Detects semantic fragment clusters, synthesizes high-value Golden Rules with parent-child
lineage, archives condensed fragments non-destructively, and supports exact decondensation.

[INPUT]
- re, time, uuid, collections.defaultdict
- .models (CompoundedExperienceItem, ExperienceItemState, GoldenRuleItem, CondensationReport)

[OUTPUT]
- KnowledgeCondensationEngine
"""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.experience_compounding.models import (
    CompoundedExperienceItem,
    CondensationReport,
    ExperienceItemState,
    GoldenRuleItem,
)

_TOKEN_SPLIT_PATTERN = re.compile(r"[\s,;，。；：\-_/]+")


def _tokenize(text: str) -> set[str]:
    """Extract normalized word and character bi-gram tokens from text."""
    lowered = text.lower().strip()
    tokens: set[str] = set()

    # 1. Word tokens for alphanumeric words
    parts = _TOKEN_SPLIT_PATTERN.split(lowered)
    for p in parts:
        if len(p) >= 2:
            tokens.add(p)

    # 2. Character bi-grams for CJK phrases
    cleaned = re.sub(r"[\s,;，。；：\-_/]+", "", lowered)
    if len(cleaned) >= 2:
        for i in range(len(cleaned) - 1):
            tokens.add(cleaned[i : i + 2])

    return tokens


def _compute_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Calculate Dice similarity coefficient between two token sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    total = len(set_a) + len(set_b)
    return (2.0 * intersection) / float(total) if total > 0 else 0.0


class KnowledgeCondensationEngine:
    """Clusters scattered experience fragments into structured Golden Rules."""

    def __init__(
        self,
        min_cluster_size: int = 2,
        similarity_threshold: float = 0.20,
    ) -> None:
        self._min_cluster_size = min_cluster_size
        self._similarity_threshold = similarity_threshold

    def condense(
        self,
        items: Sequence[CompoundedExperienceItem],
    ) -> tuple[list[GoldenRuleItem], CondensationReport]:
        """Group overlapping active fragments, synthesize Golden Rules, and archive sources."""
        report_id = f"condense-{uuid.uuid4().hex[:8]}"
        active_items = [it for it in items if it.is_active()]
        if len(active_items) < self._min_cluster_size:
            report = CondensationReport(
                report_id=report_id,
                clusters_found=0,
                rules_generated=0,
                fragments_archived=0,
                compression_ratio=0.0,
                details=["Insufficient active items to satisfy min_cluster_size threshold."],
            )
            return [], report

        # 1. Bucket by topic
        by_topic: dict[str, list[CompoundedExperienceItem]] = defaultdict(list)
        for it in active_items:
            by_topic[it.topic.lower()].append(it)

        generated_rules: list[GoldenRuleItem] = []
        total_archived = 0
        clusters_found = 0
        details: list[str] = []

        now = time.time()

        for topic, topic_items in by_topic.items():
            if len(topic_items) < self._min_cluster_size:
                continue

            # 2. Cluster items within the topic based on semantic token overlap
            clusters = self._cluster_items(topic_items)
            for cluster in clusters:
                if len(cluster) < self._min_cluster_size:
                    continue

                clusters_found += 1
                rule_id = f"rule-{uuid.uuid4().hex[:8]}"
                source_ids = [it.item_id for it in cluster]

                # Synthesize combined statement and rationale
                combined_content = "；".join(it.content.strip() for it in cluster)
                rule_stmt = f"[{topic.upper()}核心准则] {combined_content}"
                avg_confidence = min(
                    1.0,
                    sum(it.compounded_weight for it in cluster) / float(len(cluster) * 2.0),
                )

                rule = GoldenRuleItem(
                    rule_id=rule_id,
                    topic=topic,
                    rule_statement=rule_stmt,
                    rationale=f"由 {len(cluster)} 条经过高频验证的原始经验碎片聚合提炼而成",
                    confidence_score=round(avg_confidence, 3),
                    source_fragment_ids=source_ids,
                    created_at=now,
                    updated_at=now,
                )
                generated_rules.append(rule)

                # Non-destructively archive original fragments
                for it in cluster:
                    it.state = ExperienceItemState.CONDENSED_ARCHIVED
                    total_archived += 1

                details.append(
                    f"Synthesized rule {rule_id} from {len(cluster)} fragments under topic [{topic}]."
                )

        initial_count = len(active_items)
        compression_ratio = (
            round((total_archived - len(generated_rules)) / float(initial_count), 3)
            if initial_count > 0 and total_archived > 0
            else 0.0
        )

        report = CondensationReport(
            report_id=report_id,
            clusters_found=clusters_found,
            rules_generated=len(generated_rules),
            fragments_archived=total_archived,
            compression_ratio=max(0.0, compression_ratio),
            details=details,
        )
        return generated_rules, report

    def decondense(
        self,
        rule_id: str,
        rules: list[GoldenRuleItem],
        fragments: Sequence[CompoundedExperienceItem],
    ) -> list[CompoundedExperienceItem]:
        """Roll back a Golden Rule and reactivate its archived source fragments."""
        target_rule: GoldenRuleItem | None = None
        for r in rules:
            if r.rule_id == rule_id:
                target_rule = r
                break

        if target_rule is None:
            return []

        reactivated: list[CompoundedExperienceItem] = []
        target_ids = set(target_rule.source_fragment_ids)

        for f in fragments:
            if f.item_id in target_ids and f.state == ExperienceItemState.CONDENSED_ARCHIVED:
                f.state = ExperienceItemState.ACTIVE
                reactivated.append(f)

        rules.remove(target_rule)
        return reactivated

    def _cluster_items(
        self,
        items: list[CompoundedExperienceItem],
    ) -> list[list[CompoundedExperienceItem]]:
        """Greedy cluster items based on pairwise Jaccard token similarity."""
        token_map = {it.item_id: _tokenize(it.content) for it in items}
        visited: set[str] = set()
        clusters: list[list[CompoundedExperienceItem]] = []

        for i, item_a in enumerate(items):
            if item_a.item_id in visited:
                continue

            current_cluster = [item_a]
            visited.add(item_a.item_id)
            tokens_a = token_map[item_a.item_id]

            for item_b in items[i + 1 :]:
                if item_b.item_id in visited:
                    continue

                tokens_b = token_map[item_b.item_id]
                sim = _compute_similarity(tokens_a, tokens_b)
                if sim >= self._similarity_threshold:
                    current_cluster.append(item_b)
                    visited.add(item_b.item_id)

            clusters.append(current_cluster)

        return clusters
