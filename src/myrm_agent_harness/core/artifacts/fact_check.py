"""Fact Check Sheet and Multi-Source Conflict Arbitration Contract.

[INPUT]
- pydantic::BaseModel, Field
- enum::Enum
- time

[OUTPUT]
- ConflictSeverity: enum — 冲突严重程度 (critical / warning / info)
- ResolutionStatus: enum — 仲裁裁定状态 (resolved / unresolved / conditional)
- SourceClaim: class — 单个信源对特定事实的原始主张与锚点描述
- FactCheckItem: class — 单个事实核查项与多源冲突对比记录
- FactCheckSheet: class — 成套交付物事实核查单全量模型与 Markdown 渲染器

[POS]
Harness Core Layer — 业务中立的多源事实核验与冲突仲裁数据契约，提供双模导出与置信度审计。
"""

from __future__ import annotations

import time
from enum import Enum
from uuid import uuid4
from pydantic import BaseModel, Field


class ConflictSeverity(str, Enum):
    """事实冲突严重级别"""

    CRITICAL = "critical"  # 核心商业要素冲突 (如价格、交期、法务责任)
    WARNING = "warning"    # 参数规格或技术细节演进冲突
    INFO = "info"          # 措辞描述或轻微统计口径差异


class ResolutionStatus(str, Enum):
    """冲突仲裁状态"""

    RESOLVED = "resolved"        # 已确定采纳最新权威口径
    UNRESOLVED = "unresolved"    # 存在重大未决争议，需人工决策
    CONDITIONAL = "conditional"  # 根据特定前置条件分支生效


class SourceClaim(BaseModel):
    """单个素材来源的主张描述"""

    source_uri: str = Field(description="源文件路径或 URI，例如: vault://doc1.pdf")
    document_title: str = Field(description="源文档标题或文件名，例如: 内测发布会纪要.docx")
    line_anchor: str = Field(default="", description="行号或章节锚点，例如: L42-L45")
    claimed_value: str = Field(description="该素材给出的具体数据或主张，例如: 1699元")
    snippet: str = Field(default="", description="原始上下文摘录文本")
    timestamp_hint: str = Field(default="", description="素材形成时间暗示或文档版本，例如: 2026-07-15")


class FactCheckItem(BaseModel):
    """单个事实核查与口径冲突仲裁条目"""

    id: str = Field(default_factory=lambda: f"fci_{uuid4().hex[:8]}", description="核查项唯一标识")
    claim_topic: str = Field(description="核查主题/事实名称，例如: 官方首发零售价")
    severity: ConflictSeverity = Field(default=ConflictSeverity.WARNING, description="冲突严重度")
    status: ResolutionStatus = Field(default=ResolutionStatus.RESOLVED, description="仲裁状态")
    sources: list[SourceClaim] = Field(default_factory=list, description="涉及的多源素材主张列表")
    adopted_value: str = Field(description="最终在交付物中采纳的标准口径，例如: 1999元 (首发优惠1799元)")
    resolution_rationale: str = Field(description="采纳该口径的判定依据，例如: 8月20日高管定稿邮件晚于7月内测纪要")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度评分 (0.0~1.0)")
    affected_artifacts: list[str] = Field(default_factory=list, description="受该事实影响的交付物相对路径列表")
    metadata: dict[str, str] = Field(default_factory=dict, description="扩展元数据")


class FactCheckSheet(BaseModel):
    """多源事实核查与口径对比总表 (Fact Check Sheet)"""

    sheet_id: str = Field(default_factory=lambda: f"fcs_{uuid4().hex[:8]}", description="核查表唯一标识")
    session_id: str = Field(default="", description="关联的会话或任务 ID")
    title: str = Field(default="交付物多源事实核查与口径冲突对比表", description="核查表标题")
    created_at: float = Field(default_factory=time.time, description="生成时间戳")
    summary: str = Field(default="", description="核查总览或核心发现说明")
    items: list[FactCheckItem] = Field(default_factory=list, description="核查条目列表")
    metadata: dict[str, str] = Field(default_factory=dict, description="扩展元数据")

    @property
    def total_count(self) -> int:
        return len(self.items)

    @property
    def critical_count(self) -> int:
        return sum(1 for item in self.items if item.severity == ConflictSeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for item in self.items if item.severity == ConflictSeverity.WARNING)

    @property
    def unresolved_count(self) -> int:
        return sum(1 for item in self.items if item.status == ResolutionStatus.UNRESOLVED)

    def to_markdown(self) -> str:
        """纯函数生成符合 GitHub 规范的精美 Markdown 格式事实核查报告."""
        lines: list[str] = [
            f"# {self.title}",
            "",
            f"> **核查条目总数**: {self.total_count} 项 · **严重冲突**: {self.critical_count} 项 · **警告**: {self.warning_count} 项 · **待确认**: {self.unresolved_count} 项",
            f"> **生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.created_at))}",
            "",
        ]

        if self.summary:
            lines.extend([
                "## 📋 核查总览与质检摘要",
                "",
                self.summary.strip(),
                "",
            ])

        lines.extend([
            "## 🔍 事实核查与多源口径仲裁明细",
            "",
        ])

        for idx, item in enumerate(self.items, 1):
            severity_badge = {
                ConflictSeverity.CRITICAL: "🔴 严重冲突 (Critical)",
                ConflictSeverity.WARNING: "🟡 差异演进 (Warning)",
                ConflictSeverity.INFO: "🔵 描述差异 (Info)",
            }.get(item.severity, str(item.severity.value))

            status_badge = {
                ResolutionStatus.RESOLVED: "✅ 已采纳最新权威口径",
                ResolutionStatus.UNRESOLVED: "⚠️ 待人工最终确认",
                ResolutionStatus.CONDITIONAL: "🔀 按场景条件分支采纳",
            }.get(item.status, str(item.status.value))

            lines.extend([
                f"### {idx}. {item.claim_topic}",
                f"- **严重级别**: {severity_badge}",
                f"- **仲裁状态**: {status_badge} (置信度: {item.confidence_score * 100:.0f}%)",
                f"- **最终采纳标准口径**: `{item.adopted_value}`",
                f"- **取舍与仲裁依据**: {item.resolution_rationale}",
                "",
                "#### 多源素材比对对照矩阵：",
                "| 来源文档 | 原始主张数据 | 锚点/时效 | 上下文原句摘录 |",
                "| :--- | :--- | :--- | :--- |",
            ])

            for src in item.sources:
                anchor = src.line_anchor or src.timestamp_hint or "-"
                snippet_clean = src.snippet.replace("\n", " ").strip() if src.snippet else "-"
                lines.append(f"| {src.document_title} | `{src.claimed_value}` | {anchor} | {snippet_clean} |")

            if item.affected_artifacts:
                lines.extend([
                    "",
                    f"- **同步修正的交付物**: {', '.join(f'`{art}`' for art in item.affected_artifacts)}",
                ])

            lines.append("")

        return "\n".join(lines)
