"""核心引擎实现：智能体长期规则生命周期审计、过时失效嗅探与瘦身清洗中枢。

[INPUT]
- 依赖 rule_lifecycle_types.py 中的契约，标准库 pathlib, re, datetime 等。

[OUTPUT]
- AgentRuleLifecycleAuditor: 智能体规则生命周期审计中枢引擎

[POS]
- 位于 context_management/rule_lifecycle/agent_rule_lifecycle_auditor.py
"""

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Sequence

from .rule_lifecycle_types import (
    RuleAuditItem,
    RuleConflictPair,
    RuleConflictType,
    RuleLifecycleConfig,
    RuleLifecycleReport,
    RuleLifecycleState,
)


class AgentRuleLifecycleAuditor:
    """智能体长期规则生命周期审计中枢引擎。

    彻底破除智能体日久使用后 AGENTS.md/CLAUDE.md 规则无节制堆叠导致的 Prompt 臃肿、
    上下文拥挤迟钝、废弃路径与互斥矛盾“规则屎山”等痛点。
    """

    def __init__(self, config: RuleLifecycleConfig | None = None) -> None:
        self.config = config or RuleLifecycleConfig()

    def audit_rules(
        self,
        rules: Sequence[RuleAuditItem],
        workspace_root: Path | str | None = None,
    ) -> RuleLifecycleReport:
        """对智能体持久规则集合执行全面生命周期健康体检。"""
        if not rules:
            return RuleLifecycleReport(
                total_rules=0,
                healthy_rules=0,
                stale_rules=0,
                zero_hit_rules=0,
                conflicting_pairs=(),
                health_score=100.0,
                pruning_suggestions=("No rules provided to audit.",),
                audited_at_iso=datetime.now(timezone.utc).isoformat(),
            )

        root_path = Path(workspace_root).resolve() if workspace_root else None
        audited_items: list[RuleAuditItem] = []
        conflicting_pairs: list[RuleConflictPair] = []
        suggestions: list[str] = []

        # 1. 逐条审计：路径失效探测与零命中时效衰减
        seen_texts: dict[str, str] = {}  # normalized_text -> rule_id

        for rule in rules:
            conflicts: list[RuleConflictType] = list(rule.detected_conflicts)
            state = rule.state
            rec = rule.recommendation

            # 重复规则探测
            norm_text = re.sub(r"\s+", " ", rule.rule_text).strip().lower()
            if norm_text in seen_texts:
                conflicts.append(RuleConflictType.DUPLICATE_CONTENT)
                state = RuleLifecycleState.DUPLICATE_REDUNDANT
                rec = f"Duplicate of rule {seen_texts[norm_text]}; recommend merging or pruning."
            else:
                seen_texts[norm_text] = rule.rule_id

            # 工作区本地路径陈旧失效探测
            if self.config.check_local_filesystem_paths and root_path is not None:
                stale_paths = self.detect_stale_paths(rule.rule_text, root_path)
                if stale_paths:
                    conflicts.append(RuleConflictType.PATH_NOT_FOUND)
                    state = RuleLifecycleState.STALE_PATH_DETECTED
                    rec = f"Referenced path(s) not found in workspace: {', '.join(stale_paths)}."
                    suggestions.append(
                        f"Rule [{rule.rule_id}] references dead path(s): {', '.join(stale_paths)}"
                    )

            # 长期零命中时效衰减
            if (
                rule.hit_count < self.config.min_hit_count
                and rule.days_since_last_hit >= self.config.stale_days_threshold
            ):
                if state == RuleLifecycleState.ACTIVE_HEALTHY:
                    state = RuleLifecycleState.OBSOLETE_ZERO_HIT
                    rec = (
                        f"Zero hits for {rule.days_since_last_hit} days. "
                        "Recommend moving from System Prompt into on-demand memory."
                    )
                    suggestions.append(
                        f"Rule [{rule.rule_id}] has zero hits in {rule.days_since_last_hit} days."
                    )

            audited_items.append(
                RuleAuditItem(
                    rule_id=rule.rule_id,
                    rule_text=rule.rule_text,
                    source_file=rule.source_file,
                    line_number=rule.line_number,
                    hit_count=rule.hit_count,
                    days_since_last_hit=rule.days_since_last_hit,
                    state=state,
                    detected_conflicts=tuple(conflicts),
                    recommendation=rec,
                )
            )

        # 2. 互斥矛盾智能嗅探 (正面攻破 catman 提出的矛盾规则仲裁顽疾)
        if self.config.enable_semantic_conflict_check:
            detected_pairs = self.detect_contradictions(audited_items)
            conflicting_pairs.extend(detected_pairs)
            for pair in detected_pairs:
                suggestions.append(
                    f"Direct contradiction detected between [{pair.rule_id_a}] and [{pair.rule_id_b}]: "
                    f"{pair.conflict_description}"
                )

        # 3. 统计指标与健康评分
        healthy_count = sum(
            1 for r in audited_items if r.state == RuleLifecycleState.ACTIVE_HEALTHY
        )
        stale_count = sum(
            1 for r in audited_items if r.state == RuleLifecycleState.STALE_PATH_DETECTED
        )
        zero_hit_count = sum(
            1 for r in audited_items if r.state == RuleLifecycleState.OBSOLETE_ZERO_HIT
        )

        score = 100.0
        score -= len(conflicting_pairs) * self.config.conflict_penalty
        score -= stale_count * self.config.critical_stale_penalty
        score -= zero_hit_count * self.config.zero_hit_penalty
        score = max(0.0, min(100.0, score))

        if not suggestions:
            suggestions.append("Rule base is clean, agile and healthy.")

        return RuleLifecycleReport(
            total_rules=len(audited_items),
            healthy_rules=healthy_count,
            stale_rules=stale_count,
            zero_hit_rules=zero_hit_count,
            conflicting_pairs=tuple(conflicting_pairs),
            health_score=score,
            pruning_suggestions=tuple(suggestions),
            audited_at_iso=datetime.now(timezone.utc).isoformat(),
        )

    def detect_stale_paths(self, rule_text: str, root_path: Path) -> list[str]:
        """识别规则文本中提及的本地文件路径，并探测其是否已陈旧失效。"""
        # 匹配常见路径形式，如 myrm-agent/..., src/..., tests/..., *.py, *.md
        path_pattern = re.compile(
            r"(?:/[\w.-]+)+|(?:[\w.-]+/(?:[\w.-]+/)*[\w.-]+\.\w+)|(?:[\w.-]+/(?:[\w.-]+/)+)"
        )
        candidates = path_pattern.findall(rule_text)
        stale_paths: list[str] = []

        for candidate in candidates:
            # 过滤非路径伪匹配，如 MIME 类型或 URL schema
            if candidate.startswith(("http://", "https://", "application/")):
                continue
            cleaned = candidate.strip("`'\",:;()[]")
            if not cleaned or len(cleaned) < 4:
                continue

            target = (root_path / cleaned).resolve()
            # 仅校验位于当前工作区内的相对或绝对目标
            if not target.exists():
                stale_paths.append(cleaned)

        return stale_paths

    def detect_contradictions(
        self,
        rules: Sequence[RuleAuditItem],
    ) -> list[RuleConflictPair]:
        """检测正反互斥矛盾 (如强制某行为 vs 禁止某行为)。"""
        pairs: list[RuleConflictPair] = []
        pos_keywords = ("必须", "强制", "ALWAYS", "MUST", "REQUIRED", "REQUIRE")
        neg_keywords = ("禁止", "严禁", "NEVER", "FORBID", "PROHIBITED", "NO")

        # 实体对偶抽词
        for i in range(len(rules)):
            for j in range(i + 1, len(rules)):
                r1 = rules[i]
                r2 = rules[j]
                text1 = r1.rule_text.upper()
                text2 = r2.rule_text.upper()

                r1_pos = any(kw in text1 for kw in pos_keywords)
                r1_neg = any(kw in text1 for kw in neg_keywords)
                r2_pos = any(kw in text2 for kw in pos_keywords)
                r2_neg = any(kw in text2 for kw in neg_keywords)

                # 互斥特征：一条包含强制，另一条包含禁止
                has_polarity_clash = (r1_pos and r2_neg) or (r1_neg and r2_pos)
                if not has_polarity_clash:
                    continue

                # 提取潜在共同操作目标 (如 "ANY", "注释", "缓存", "全局", "并发", "重构")
                common_tokens = self._extract_common_subject_tokens(text1, text2)
                if common_tokens:
                    pairs.append(
                        RuleConflictPair(
                            rule_id_a=r1.rule_id,
                            rule_id_b=r2.rule_id,
                            conflict_type=RuleConflictType.DIRECT_CONTRADICTION,
                            conflict_description=(
                                f"Direct contradictory directive regarding [{', '.join(common_tokens)}]. "
                                f"One rule mandates it while the other forbids it."
                            ),
                            resolution_advice=(
                                f"Explicitly decide whether to allow or forbid [{', '.join(common_tokens)}] "
                                "to eliminate agent hesitation or hallucination."
                            ),
                        )
                    )

        return pairs

    def prune_and_slim(
        self,
        rules: Sequence[RuleAuditItem],
        remove_stale: bool = True,
        remove_duplicates: bool = True,
        remove_zero_hits: bool = False,
    ) -> tuple[tuple[RuleAuditItem, ...], int]:
        """执行规则瘦身与清洗，剔除无效、重复或陈旧规则。"""
        retained: list[RuleAuditItem] = []
        pruned_count = 0

        for r in rules:
            should_prune = False
            if remove_duplicates and r.state == RuleLifecycleState.DUPLICATE_REDUNDANT:
                should_prune = True
            elif remove_stale and r.state == RuleLifecycleState.STALE_PATH_DETECTED:
                should_prune = True
            elif remove_zero_hits and r.state == RuleLifecycleState.OBSOLETE_ZERO_HIT:
                should_prune = True

            if should_prune:
                pruned_count += 1
            else:
                retained.append(r)

        return tuple(retained), pruned_count

    def _extract_common_subject_tokens(self, text_a: str, text_b: str) -> list[str]:
        """提取两段规则中潜在的核心冲突概念名词。"""
        # 常用敏感动作与技术概念
        candidates = (
            "ANY",
            "MOCK",
            "CACHE",
            "ASYNC",
            "REFACTOR",
            "GLOBAL",
            "TEST",
            "注释",
            "缓存",
            "并发",
            "全局",
            "重构",
            "单例",
        )
        return [c for c in candidates if c in text_a and c in text_b]
