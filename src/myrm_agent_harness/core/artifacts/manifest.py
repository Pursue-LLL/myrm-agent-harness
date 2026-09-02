"""Deliverable Manifest and Bundle Data Contract.

[INPUT]
- pydantic::BaseModel, Field
- myrm_agent_harness.core.artifacts.constants::ArtifactType

[OUTPUT]
- DeliverableItem: class — 单个交付工件的元数据和相对路径描述
- DeliverableCategory: enum — 交付物标准分类
- DeliverableManifest: class — 一揽子成套交付物清单规范

[POS]
Harness Core Layer — 业务中立的成套交付物标准契约，提供版本快照、逻辑目录树与哈希校验。
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Mapping
from pydantic import BaseModel, Field


class DeliverableCategory(str, Enum):
    """交付物标准分类枚举"""

    ARTICLE = "article"  # 深度文章、公众号、专栏等长文
    SOCIAL_POST = "social_post"  # 小红书、微博、朋友圈、推特等短图文
    SCRIPT = "script"  # 短视频分镜脚本、播客脚本、主持稿
    DATA_SHEET = "data_sheet"  # Excel/CSV 排期表、数据统计表
    VISUAL_ASSET = "visual_asset"  # 封面图、信息图、配图、海报
    REPORT = "report"  # 商业研报、调研分析、复盘报告
    FACT_CHECK = "fact_check"  # 事实核查表、冲突仲裁证据表
    CODE_ASSET = "code_asset"  # 交付的代码包、Notebook、脚本
    PRESENTATION = "presentation"  # PPTX / 演示幻灯片
    OTHER = "other"  # 其他通用成果物


class DeliverableItem(BaseModel):
    """成套交付物中的单项工件元数据"""

    id: str = Field(description="工件唯一标识")
    relative_path: str = Field(
        description="在交付包逻辑目录中的相对路径，例如: articles/wechat_main.md"
    )
    title: str = Field(description="交付物名称/标题")
    category: DeliverableCategory = Field(
        default=DeliverableCategory.OTHER, description="交付物分类"
    )
    vault_uri: str = Field(description="Vault 存储指针 (vault://<uuid>)")
    sha256_hash: str = Field(default="", description="工件内容的 SHA-256 哈希值")
    size_bytes: int = Field(default=0, ge=0, description="工件字节大小")
    mime_type: str = Field(default="application/octet-stream", description="MIME 类型")
    version_id: str = Field(default="", description="锁定的不可变工件版本 ID")
    description: str = Field(default="", description="交付物说明或业务用途")
    metadata: dict[str, str] = Field(
        default_factory=dict, description="业务元数据 (如尺寸、字数、平台等)"
    )


class DeliverableManifest(BaseModel):
    """成套交付物清单 (Deliverable Manifest)"""

    bundle_id: str = Field(description="交付包唯一标识 (UUID)")
    session_id: str = Field(description="关联的会话或任务 ID")
    title: str = Field(description="交付包总标题，如: 9月新品全渠道宣发物料全案")
    created_at: float = Field(default_factory=time.time, description="生成时间戳")
    agent_id: str = Field(default="", description="产出该交付包的智能体 ID")
    task_prompt: str = Field(default="", description="触发本次交付的原始任务意图")
    items: list[DeliverableItem] = Field(
        default_factory=list, description="交付物清单列表"
    )
    metadata: dict[str, str] = Field(default_factory=dict, description="扩展元数据")

    @property
    def total_count(self) -> int:
        return len(self.items)

    @property
    def total_size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)

    def category_summary(self) -> dict[str, int]:
        """统计各类目交付物数量"""
        summary: dict[str, int] = {}
        for item in self.items:
            cat = item.category.value
            summary[cat] = summary.get(cat, 0) + 1
        return summary
