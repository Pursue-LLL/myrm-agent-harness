"""多代理共享草稿白板、子代理瞬态上下文隔离与轻量事实广播套件强类型契约定义。

[INPUT]
- 无外部动态依赖，定义事实类别枚举、子代理生命周期枚举、共享白板事实条目与瞬态档案契约。

[OUTPUT]
- FactCategory: 共享事实类别枚举 (API_SPEC, DISCOVERED_DOC, ANTI_PATTERN_PITFALL, TASK_MILESTONE, ENVIRONMENT_TRUTH)
- SubagentLifecycleStatus: 子代理生命周期状态枚举 (ACTIVE, COMPLETED, GARBAGE_COLLECTED)
- SharedScratchpadFact: 共享草稿白板事实条目契约
- EphemeralSubagentDossier: 子代理瞬态隔离档案契约
- ScratchpadQueryFilter: 事实白板检索过滤契约

[POS]
- 位于 context_management/subagent_scratchpad/subagent_scratchpad_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class FactCategory(StrEnum):
    """共享事实分类枚举。"""

    API_SPEC = "api_spec"                     # 已查明的接口规格/参数结构
    DISCOVERED_DOC = "discovered_doc"         # 已拉取的长文档高密摘要
    ANTI_PATTERN_PITFALL = "anti_pattern"     # 已踩坑/已证伪路线（禁止后续 Agent 重复尝试）
    TASK_MILESTONE = "task_milestone"         # 阶段性里程碑完成信号
    ENVIRONMENT_TRUTH = "environment_truth"   # 运行时环境既定事实（如已占用端口、版本号等）


class SubagentLifecycleStatus(StrEnum):
    """子代理生命周期状态枚举。"""

    ACTIVE = "active"
    COMPLETED = "completed"
    GARBAGE_COLLECTED = "garbage_collected"


@dataclass(frozen=True)
class SharedScratchpadFact:
    """共享草稿白板权威事实条目契约。"""

    fact_id: str
    cluster_id: str
    category: FactCategory
    key: str
    summary: str
    details: str
    discovered_by_subagent_id: str
    confidence: float  # 0.0 ~ 1.0 置信度
    created_at_iso: str


@dataclass(frozen=True)
class EphemeralSubagentDossier:
    """子代理瞬态隔离上下文档案契约。"""

    subagent_id: str
    cluster_id: str
    role_name: str
    status: SubagentLifecycleStatus
    transient_logs_count: int
    promoted_fact_ids: tuple[str, ...]
    registered_at_iso: str
    collected_at_iso: str | None = None


@dataclass(frozen=True)
class ScratchpadQueryFilter:
    """白板事实检索过滤条件。"""

    category: FactCategory | None = None
    keyword: str | None = None
    min_confidence: float = 0.7
