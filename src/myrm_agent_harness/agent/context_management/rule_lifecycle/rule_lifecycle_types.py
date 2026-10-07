"""强类型契约定义：智能体长期规则生命周期审计、过时失效嗅探与瘦身清洗套件。

[INPUT]
- 无外部动态依赖，定义规则生命周期状态、冲突类型、冲突对、审计项及健康度报告契约。

[OUTPUT]
- RuleLifecycleState: 规则生命周期健康状态枚举
- RuleConflictType: 规则冲突与陈旧失效类型枚举
- RuleConflictPair: 正反互斥或冗余冲突对契约
- RuleAuditItem: 单条规则审计条目契约
- RuleLifecycleReport: 规则体系全局体检与瘦身审计报告契约
- RuleLifecycleConfig: 规则生命周期审计配置契约

[POS]
- 位于 context_management/rule_lifecycle/rule_lifecycle_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence


class RuleLifecycleState(StrEnum):
    """规则生命周期健康状态。"""

    ACTIVE_HEALTHY = "active_healthy"
    STALE_PATH_DETECTED = "stale_path_detected"
    CONTRADICTION_CONFLICT = "contradiction_conflict"
    OBSOLETE_ZERO_HIT = "obsolete_zero_hit"
    DUPLICATE_REDUNDANT = "duplicate_redundant"


class RuleConflictType(StrEnum):
    """规则冲突与失效归类。"""

    PATH_NOT_FOUND = "path_not_found"
    DIRECT_CONTRADICTION = "direct_contradiction"
    COMMAND_DEPRECATED = "command_deprecated"
    DUPLICATE_CONTENT = "duplicate_content"


@dataclass(frozen=True)
class RuleConflictPair:
    """互斥矛盾或冗余冲突对契约。"""

    rule_id_a: str
    rule_id_b: str
    conflict_type: RuleConflictType
    conflict_description: str
    resolution_advice: str


@dataclass(frozen=True)
class RuleAuditItem:
    """单条规则审计条目契约。"""

    rule_id: str
    rule_text: str
    source_file: str = "AGENTS.md"
    line_number: int = 1
    hit_count: int = 0
    days_since_last_hit: int = 0
    state: RuleLifecycleState = RuleLifecycleState.ACTIVE_HEALTHY
    detected_conflicts: tuple[RuleConflictType, ...] = field(default_factory=tuple)
    recommendation: str = ""


@dataclass(frozen=True)
class RuleLifecycleReport:
    """规则体系全局体检与瘦身审计报告契约。"""

    total_rules: int
    healthy_rules: int
    stale_rules: int
    zero_hit_rules: int
    conflicting_pairs: tuple[RuleConflictPair, ...]
    health_score: float  # 0.0 ~ 100.0
    pruning_suggestions: tuple[str, ...]
    audited_at_iso: str


@dataclass
class RuleLifecycleConfig:
    """规则生命周期审计配置契约。"""

    stale_days_threshold: int = 30
    min_hit_count: int = 1
    check_local_filesystem_paths: bool = True
    enable_semantic_conflict_check: bool = True
    critical_stale_penalty: float = 15.0
    conflict_penalty: float = 20.0
    zero_hit_penalty: float = 5.0
