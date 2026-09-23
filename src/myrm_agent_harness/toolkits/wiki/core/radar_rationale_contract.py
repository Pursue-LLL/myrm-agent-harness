"""Contract for Three-Way Knowledge Radar and Zero-Yield Rationale Report.

[INPUT]
- utils.markdown_frontmatter (POS: parse_frontmatter)

[OUTPUT]
- RadarYieldDecision, ZeroYieldRationaleReport, format_zero_yield_report, parse_zero_yield_report

[POS]
Defines three-way source radar ingestion contract (Deep Research + Report Retrieval + Web Baseline)
and formal Zero-Yield Rationale Reports to prevent hallucinated/substandard batch injection into the wiki.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

RadarYieldDecision = Literal["yield_collected", "zero_yield_suppressed"]


@dataclass(frozen=True, slots=True)
class ZeroYieldRationaleReport:
    """Formal rationale report emitted when a radar probe produces no qualifying knowledge."""

    batch_id: str
    query_topic: str
    executed_at: str
    deep_research_candidates: int
    report_candidates: int
    web_baseline_candidates: int
    yield_decision: RadarYieldDecision
    rationale: str
    suggested_next_probe: str = ""

    def to_frontmatter_dict(self) -> dict[str, object]:
        """Convert to dict for YAML frontmatter."""
        data = asdict(self)
        data["type"] = "radar_report"
        return data


def format_zero_yield_report(report: ZeroYieldRationaleReport) -> str:
    """Serialize a ZeroYieldRationaleReport into a clean markdown document."""
    import yaml

    fm_dict = report.to_frontmatter_dict()
    header = yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True).strip()
    body = (
        f"# 雷达探测理由报告: {report.query_topic}\n\n"
        f"- **批次号 (Batch ID)**: `{report.batch_id}`\n"
        f"- **执行时间 (UTC)**: {report.executed_at}\n"
        f"- **三路探测明细**:\n"
        f"  - 深度调研 (Deep Research): 召回 {report.deep_research_candidates} 项（达标 0）\n"
        f"  - 行业研报 (Report Retrieval): 召回 {report.report_candidates} 项（达标 0）\n"
        f"  - 网络基线 (Web Baseline): 召回 {report.web_baseline_candidates} 项（达标 0）\n"
        f"- **决策判定**: **宁缺毋滥，拦截入库 ({report.yield_decision})**\n\n"
        f"### 拦截理由 (Rationale)\n{report.rationale}\n\n"
    )
    if report.suggested_next_probe:
        body += f"### 下次探测建议\n{report.suggested_next_probe}\n"
    return f"---\n{header}\n---\n\n{body}"


def parse_zero_yield_report(content: str) -> ZeroYieldRationaleReport:
    """Parse markdown content into ZeroYieldRationaleReport."""
    metadata, body = parse_frontmatter(content)
    batch_id = str(metadata.get("batch_id") or "batch_unknown").strip()
    query_topic = str(metadata.get("query_topic") or "General Radar").strip()
    executed_at = str(
        metadata.get("executed_at") or datetime.now(UTC).isoformat(timespec="seconds")
    ).strip()
    deep_c = int(metadata.get("deep_research_candidates") or 0)
    rep_c = int(metadata.get("report_candidates") or 0)
    web_c = int(metadata.get("web_baseline_candidates") or 0)
    raw_decision = str(metadata.get("yield_decision") or "zero_yield_suppressed").strip()
    yield_decision: RadarYieldDecision = (
        "yield_collected" if raw_decision == "yield_collected" else "zero_yield_suppressed"
    )
    rationale = str(metadata.get("rationale") or body.strip()).strip()
    suggested_next_probe = str(metadata.get("suggested_next_probe") or "").strip()

    return ZeroYieldRationaleReport(
        batch_id=batch_id,
        query_topic=query_topic,
        executed_at=executed_at,
        deep_research_candidates=deep_c,
        report_candidates=rep_c,
        web_baseline_candidates=web_c,
        yield_decision=yield_decision,
        rationale=rationale,
        suggested_next_probe=suggested_next_probe,
    )
