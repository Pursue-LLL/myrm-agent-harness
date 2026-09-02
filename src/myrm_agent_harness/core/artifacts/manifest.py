"""Deliverable Manifest and Bundle Data Contract.

[INPUT]
- pydantic::BaseModel, Field
- myrm_agent_harness.core.artifacts.constants::ArtifactType

[OUTPUT]
- DeliverableItem: class — 单个交付工件的元数据和相对路径描述
- DeliverableCategory: enum — 交付物标准分类
- DeliverableStatus: enum — 交付物就绪状态
- DeliverableManifest: class — 一揽子成套交付物清单规范
- CATEGORY_DIRECTORY_MAPPING: dict — 标准目录名映射字典
- infer_item_category: function — 从文件名推断分类

[POS]
Harness Core Layer — 业务中立的成套交付物标准契约，提供版本快照、逻辑目录树与哈希校验。
"""

from __future__ import annotations

import os
import time
from enum import Enum
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field, model_validator


class DeliverableCategory(str, Enum):
    """交付物标准分类枚举"""

    STRATEGY = "strategy"  # 策略规划与方案全案
    COPYWRITING = "copywriting"  # 文案与内容创作
    VISUAL = "visual"  # 视觉与媒体资产
    DATA_SHEET = "data_sheet"  # 数据表与排期表
    FACT_CHECK = "fact_check"  # 事实核查与审计单
    SCHEDULE = "schedule"  # 项目计划与时间表
    CODE = "code"  # 交付代码与脚本
    ARTICLE = "article"  # 深度文章、公众号、专栏等长文
    SOCIAL_POST = "social_post"  # 小红书、微博、朋友圈、推特等短图文
    SCRIPT = "script"  # 短视频分镜脚本、播客脚本、主持稿
    VISUAL_ASSET = "visual_asset"  # 封面图、信息图、配图、海报
    REPORT = "report"  # 商业研报、调研分析、复盘报告
    CODE_ASSET = "code_asset"  # 交付的代码包、Notebook、脚本
    PRESENTATION = "presentation"  # PPTX / 演示幻灯片
    OTHER = "other"  # 其他通用成果物


class DeliverableStatus(str, Enum):
    """Verification and distribution readiness status."""

    DRAFT = "draft"
    VERIFIED = "verified"
    READY_FOR_DISTRIBUTION = "ready_for_distribution"


# Standard folder names by category
CATEGORY_DIRECTORY_MAPPING: dict[DeliverableCategory, str] = {
    DeliverableCategory.STRATEGY: "01_strategy_and_overview",
    DeliverableCategory.COPYWRITING: "02_copywriting_and_content",
    DeliverableCategory.ARTICLE: "02_copywriting_and_content",
    DeliverableCategory.SOCIAL_POST: "02_copywriting_and_content",
    DeliverableCategory.SCRIPT: "02_copywriting_and_content",
    DeliverableCategory.VISUAL: "03_visual_and_media",
    DeliverableCategory.VISUAL_ASSET: "03_visual_and_media",
    DeliverableCategory.DATA_SHEET: "04_data_and_sheets",
    DeliverableCategory.FACT_CHECK: "05_fact_check_and_audit",
    DeliverableCategory.SCHEDULE: "06_schedule_and_plans",
    DeliverableCategory.CODE: "07_code_and_scripts",
    DeliverableCategory.CODE_ASSET: "07_code_and_scripts",
    DeliverableCategory.REPORT: "01_strategy_and_overview",
    DeliverableCategory.PRESENTATION: "03_visual_and_media",
    DeliverableCategory.OTHER: "08_misc_deliverables",
}


def infer_item_category(filename: str) -> DeliverableCategory:
    """Infer deliverable category from filename conventions and extension."""
    lower = filename.lower()
    if any(k in lower for k in ("fact_check", "factcheck", "verification", "audit")):
        return DeliverableCategory.FACT_CHECK
    if any(k in lower for k in ("schedule", "calendar", "timeline", "plan_7days", "7days_schedule")):
        return DeliverableCategory.SCHEDULE
    if any(k in lower for k in ("strategy", "proposal", "brief", "summary", "report")):
        return DeliverableCategory.STRATEGY
    if any(
        k in lower
        for k in (
            "wechat",
            "xhs",
            "xiaohongshu",
            "douyin",
            "script",
            "copy",
            "article",
            "post",
        )
    ):
        return DeliverableCategory.COPYWRITING
    if lower.endswith(
        (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".mp4", ".mp3", ".wav")
    ):
        return DeliverableCategory.VISUAL
    if lower.endswith((".xlsx", ".xls", ".csv")):
        return DeliverableCategory.DATA_SHEET
    if lower.endswith((".py", ".ts", ".js", ".sh", ".sql", ".rs", ".go")):
        return DeliverableCategory.CODE
    return DeliverableCategory.OTHER


class DeliverableItem(BaseModel):
    """成套交付物中的单项工件元数据"""

    id: str = Field(description="工件唯一标识")
    filename: str = Field(default="", description="工件文件名")
    relative_path: str = Field(
        default="",
        description="在交付包逻辑目录中的相对路径，例如: articles/wechat_main.md",
    )
    title: str = Field(default="", description="交付物名称/标题")
    category: DeliverableCategory = Field(
        default=DeliverableCategory.OTHER, description="交付物分类"
    )
    platform: str | None = Field(
        default=None, description="发布平台标识 (如 xiaohongshu, wechat)"
    )
    vault_uri: str = Field(default="", description="Vault 存储指针 (vault://<uuid>)")
    sha256_hash: str = Field(default="", description="工件内容的 SHA-256 哈希值")
    size_bytes: int = Field(default=0, ge=0, description="工件字节大小")
    mime_type: str = Field(default="application/octet-stream", description="MIME 类型")
    status: DeliverableStatus = Field(
        default=DeliverableStatus.READY_FOR_DISTRIBUTION, description="交付状态"
    )
    version_id: str = Field(default="", description="锁定的不可变工件版本 ID")
    description: str = Field(default="", description="交付物说明或业务用途")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="业务元数据 (如尺寸、字数、平台等)"
    )

    @model_validator(mode="after")
    def _fill_filename_or_path(self) -> DeliverableItem:
        if not self.filename and self.relative_path:
            self.filename = os.path.basename(self.relative_path)
        elif not self.relative_path and self.filename:
            self.relative_path = self.filename
        if not self.title and self.filename:
            self.title = self.filename
        return self


class DeliverableManifest(BaseModel):
    """成套交付物清单 (Deliverable Manifest)"""

    bundle_id: str = Field(
        default_factory=lambda: str(uuid4()), description="交付包唯一标识 (UUID)"
    )
    session_id: str = Field(default="", description="关联的会话或任务 ID")
    title: str = Field(default="Deliverable Package", description="交付包总标题")
    description: str = Field(default="", description="交付包描述")
    created_at: float = Field(default_factory=time.time, description="生成时间戳")
    agent_id: str | None = Field(default=None, description="产出该交付包的智能体 ID")
    goal_id: str | None = Field(default=None, description="关联的目标 ID")
    task_prompt: str = Field(default="", description="触发本次交付的原始任务意图")
    items: list[DeliverableItem] = Field(
        default_factory=list, description="交付物清单列表"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")

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
