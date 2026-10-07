"""强类型契约定义：长文本入站防御性分页挂载、大消息防爆 Working Memory 与智能摘要网关套件。

[INPUT]
- 无外部动态依赖，定义入站消息分类、挂载元数据、屏蔽拦截结果与网关配置契约。

[OUTPUT]
- InboundPayloadClassification: 入站有效载荷分类枚举 (直通 / 拦截挂载 / 极端超长)
- InboundMountedDocument: 挂载入沙箱工作区的大文本元数据契约
- InboundShieldResult: 防御拦截与指针注入结果契约
- InboundShieldConfig: 消息体积守门员与工作区挂载配置契约

[POS]
- 位于 context_management/inbound_shield/inbound_shield_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class InboundPayloadClassification(StrEnum):
    """入站消息体积分级分类。"""

    SAFE_PASS_THROUGH = "safe_pass_through"
    OVERSIZED_TRUNCATED_AND_MOUNTED = "oversized_truncated_and_mounted"
    EXTREME_PAYLOAD_CLAMPED = "extreme_payload_clamped"


@dataclass(frozen=True)
class InboundMountedDocument:
    """挂载至沙箱工作区的大文本物理文档元数据。"""

    mount_id: str
    relative_path: str
    absolute_path: str
    char_count: int
    estimated_tokens: int
    sha256_hash: str
    skeleton_summary: str
    created_at_iso: str
    key_entities: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class InboundShieldResult:
    """长消息入站防御拦截与指针注入结果契约。"""

    is_intercepted: bool
    classification: InboundPayloadClassification
    shielded_content: str
    mounted_doc: InboundMountedDocument | None
    original_chars: int
    original_estimated_tokens: int
    effective_tokens: int
    saved_tokens: int
    read_tool_guidance: str | None = None


@dataclass
class InboundShieldConfig:
    """入站大消息防爆栅栏配置契约。"""

    char_threshold: int = 4000
    token_threshold: int = 1000
    extreme_char_threshold: int = 500_000
    max_skeleton_summary_chars: int = 350
    mount_directory_relative: str = ".context/inbound"
    enable_auto_mounting: bool = True
    extract_outline_headers: bool = True
    preview_head_chars: int = 350
    preview_tail_chars: int = 250
