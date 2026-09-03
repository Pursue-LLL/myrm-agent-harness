"""Unit tests for FactCheckSheet, FactCheckItem, SourceClaim contracts and Markdown rendering."""

from __future__ import annotations

import json
from myrm_agent_harness.core.artifacts.fact_check import (
    ConflictSeverity,
    FactCheckItem,
    FactCheckSheet,
    ResolutionStatus,
    SourceClaim,
)


class TestFactCheckEnums:
    def test_conflict_severity_values(self) -> None:
        assert ConflictSeverity.CRITICAL == "critical"
        assert ConflictSeverity.WARNING == "warning"
        assert ConflictSeverity.INFO == "info"
        assert isinstance(ConflictSeverity.CRITICAL, str)

    def test_resolution_status_values(self) -> None:
        assert ResolutionStatus.RESOLVED == "resolved"
        assert ResolutionStatus.UNRESOLVED == "unresolved"
        assert ResolutionStatus.CONDITIONAL == "conditional"
        assert isinstance(ResolutionStatus.RESOLVED, str)


class TestSourceClaim:
    def test_source_claim_creation(self) -> None:
        claim = SourceClaim(
            source_uri="vault://meeting_minutes.docx",
            document_title="内测发布会纪要.docx",
            line_anchor="L42-L45",
            claimed_value="1699元",
            snippet="首批受邀客户可享受内测价 1699 元。",
            timestamp_hint="2026-07-15",
        )
        assert claim.source_uri == "vault://meeting_minutes.docx"
        assert claim.document_title == "内测发布会纪要.docx"
        assert claim.line_anchor == "L42-L45"
        assert claim.claimed_value == "1699元"
        assert claim.snippet == "首批受邀客户可享受内测价 1699 元。"
        assert claim.timestamp_hint == "2026-07-15"

    def test_source_claim_defaults(self) -> None:
        claim = SourceClaim(
            source_uri="vault://memo.pdf",
            document_title="备忘录.pdf",
            claimed_value="全员持股",
        )
        assert claim.line_anchor == ""
        assert claim.snippet == ""
        assert claim.timestamp_hint == ""


class TestFactCheckItem:
    def test_item_default_id_and_fields(self) -> None:
        item = FactCheckItem(
            claim_topic="官方首发零售价",
            adopted_value="1999元 (首发优惠1799元)",
            resolution_rationale="8月20日高管定稿邮件晚于7月内测纪要，以最终上市通告为准",
        )
        assert item.id.startswith("fci_")
        assert item.severity == ConflictSeverity.WARNING
        assert item.status == ResolutionStatus.RESOLVED
        assert item.confidence_score == 1.0
        assert item.sources == []
        assert item.affected_artifacts == []
        assert item.metadata == {}

    def test_item_custom_fields(self) -> None:
        src1 = SourceClaim(
            source_uri="vault://doc1.docx",
            document_title="草案.docx",
            claimed_value="1699元",
        )
        src2 = SourceClaim(
            source_uri="vault://doc2.pdf",
            document_title="正式发布通告.pdf",
            claimed_value="1999元",
        )
        item = FactCheckItem(
            claim_topic="官方首发零售价",
            severity=ConflictSeverity.CRITICAL,
            status=ResolutionStatus.RESOLVED,
            sources=[src1, src2],
            adopted_value="1999元",
            resolution_rationale="以后者权威发布通告为准",
            confidence_score=0.98,
            affected_artifacts=["01_articles/launch_announcement.md"],
            metadata={"reviewer": "chief_editor"},
        )
        assert item.severity == ConflictSeverity.CRITICAL
        assert len(item.sources) == 2
        assert item.affected_artifacts == ["01_articles/launch_announcement.md"]
        assert item.metadata["reviewer"] == "chief_editor"


class TestFactCheckSheet:
    def test_sheet_properties(self) -> None:
        item1 = FactCheckItem(
            claim_topic="核心定价",
            severity=ConflictSeverity.CRITICAL,
            status=ResolutionStatus.RESOLVED,
            adopted_value="1999元",
            resolution_rationale="定稿通告",
        )
        item2 = FactCheckItem(
            claim_topic="电池续航",
            severity=ConflictSeverity.WARNING,
            status=ResolutionStatus.UNRESOLVED,
            adopted_value="待确认",
            resolution_rationale="实验室数据与样机实测存在偏差",
        )
        item3 = FactCheckItem(
            claim_topic="包装清单",
            severity=ConflictSeverity.INFO,
            status=ResolutionStatus.CONDITIONAL,
            adopted_value="含充电线",
            resolution_rationale="环保版不含头",
        )

        sheet = FactCheckSheet(
            sheet_id="fcs_test001",
            session_id="sess_12345",
            title="产品发布物料多源事实核查表",
            summary="发现 1 处严重价格冲突，1 处待确认续航参数",
            items=[item1, item2, item3],
        )

        assert sheet.total_count == 3
        assert sheet.critical_count == 1
        assert sheet.warning_count == 1
        assert sheet.unresolved_count == 1

    def test_sheet_to_markdown_rendering(self) -> None:
        src = SourceClaim(
            source_uri="vault://memo.docx",
            document_title="纪要.docx",
            line_anchor="L12",
            claimed_value="1699元",
            snippet="首发特惠价 1699 元\n第二件半价",
        )
        item = FactCheckItem(
            claim_topic="首发价",
            severity=ConflictSeverity.CRITICAL,
            status=ResolutionStatus.RESOLVED,
            sources=[src],
            adopted_value="1999元",
            resolution_rationale="高管决议邮件晚于讨论纪要",
            confidence_score=0.95,
            affected_artifacts=["01_articles/launch.md"],
        )
        sheet = FactCheckSheet(
            title="测试核查单",
            summary="质检摘要：核验通过",
            items=[item],
        )

        md = sheet.to_markdown()
        assert "# 测试核查单" in md
        assert "**核查条目总数**: 1 项" in md
        assert "**严重冲突**: 1 项" in md
        assert "## 📋 核查总览与质检摘要" in md
        assert "质检摘要：核验通过" in md
        assert "## 🔍 事实核查与多源口径仲裁明细" in md
        assert "### 1. 首发价" in md
        assert "🔴 严重冲突 (Critical)" in md
        assert "✅ 已采纳最新权威口径" in md
        assert "`1999元`" in md
        assert "高管决议邮件晚于讨论纪要" in md
        assert "| 纪要.docx | `1699元` | L12 |" in md
        assert "首发特惠价 1699 元 第二件半价" in md
        assert "01_articles/launch.md" in md

    def test_sheet_json_serialization_roundtrip(self) -> None:
        item = FactCheckItem(
            claim_topic="质保期限",
            severity=ConflictSeverity.WARNING,
            status=ResolutionStatus.RESOLVED,
            adopted_value="2年整机质保",
            resolution_rationale="国家标准+品牌延长保障",
            confidence_score=1.0,
        )
        sheet = FactCheckSheet(
            sheet_id="fcs_json_test",
            title="质保条款核验",
            items=[item],
        )

        json_str = sheet.model_dump_json()
        data = json.loads(json_str)
        assert data["sheet_id"] == "fcs_json_test"
        assert len(data["items"]) == 1

        reloaded = FactCheckSheet.model_validate(data)
        assert reloaded.sheet_id == "fcs_json_test"
        assert reloaded.items[0].claim_topic == "质保期限"

    def test_empty_sheet_to_markdown(self) -> None:
        sheet = FactCheckSheet(
            sheet_id="fcs_empty",
            title="空核查单",
            items=[],
        )
        md = sheet.to_markdown()
        assert "# 空核查单" in md
        assert "**核查条目总数**: 0 项" in md
        assert "## 🔍 事实核查与多源口径仲裁明细" in md
