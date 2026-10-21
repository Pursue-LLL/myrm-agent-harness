"""Automated issue triage, complexity evaluation, and fix proposal generator.

Benchmarked against Today Huajuan autonomous issue scanning:
- Evaluates open issues across tracked repositories.
- Assesses priority, suspected affected files, and implementation risk.
- Generates structured FixPlanProposal models for user selection.
- Produces actionable GitHub Flavored Markdown summary cards.

[OUTPUT]
- IssueScannerAndPlanner: Triages open issues and prepares fix plans.

[INPUT]
- __future__
- re
- uuid

[OUTPUT]
- IssueScannerAndPlanner

[POS]
Automated issue triage, complexity evaluation, and fix proposal generator.
"""

from __future__ import annotations

import re
import uuid

from myrm_agent_harness.runtime.issue_resolution.pipeline_types import (
    FixPlanProposal,
    IssuePriority,
    IssueResolutionStatus,
    RepositoryIssue,
)


class IssueScannerAndPlanner:
    """Scans repository issues and formulates actionable automated fix proposals."""

    @staticmethod
    def assess_priority(issue: RepositoryIssue) -> IssuePriority:
        """Derive issue priority from labels and textual sentiment."""
        labels_lower = {lb.lower() for lb in issue.labels}
        text_lower = f"{issue.title} {issue.body}".lower()

        if any(kw in labels_lower or kw in text_lower for kw in ("security", "critical", "cve", "p0", "crash")):
            return IssuePriority.CRITICAL
        if any(kw in labels_lower or kw in text_lower for kw in ("bug", "regression", "p1", "error", "broken")):
            return IssuePriority.HIGH
        if any(kw in labels_lower or kw in text_lower for kw in ("enhancement", "feature", "p2", "improvement")):
            return IssuePriority.MEDIUM
        return IssuePriority.LOW

    @staticmethod
    def extract_affected_files(text: str) -> tuple[str, ...]:
        """Detect referenced file paths within the issue body."""
        pattern = r"\b(?:[a-zA-Z0-9_.-]+/)+[a-zA-Z0-9_.-]+\.(?:py|ts|tsx|js|json|md|yml|yaml)\b"
        matches = re.findall(pattern, text)
        # Deduplicate preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for match in matches:
            if match not in seen:
                seen.add(match)
                deduped.append(match)
        return tuple(deduped)

    def generate_proposal(
        self,
        issue: RepositoryIssue,
        default_target_branch: str = "main",
    ) -> FixPlanProposal:
        """Synthesize an actionable fix plan proposal for a given issue."""
        priority = self.assess_priority(issue)
        detected_files = self.extract_affected_files(issue.body)
        files = detected_files if detected_files else (f"src/{issue.repo.split('/')[-1]}/main.py",)

        # Risk assessment based on priority and scope
        risk_level = "Low" if len(files) <= 2 and priority in (IssuePriority.LOW, IssuePriority.MEDIUM) else "Medium"
        if priority == IssuePriority.CRITICAL or len(files) > 4:
            risk_level = "High"

        confidence = 0.95 if detected_files else 0.80

        summary = (
            f"Fix issue #{issue.issue_id} ({issue.title}). "
            f"Address root cause in {', '.join(files[:3])} with regression unit tests."
        )

        return FixPlanProposal(
            proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
            issue_id=issue.issue_id,
            repo=issue.repo,
            target_branch=default_target_branch,
            plan_summary=summary,
            affected_files=files,
            estimated_risk=risk_level,
            automated_confidence=confidence,
        )

    def scan_and_plan(
        self,
        issues: list[RepositoryIssue] | tuple[RepositoryIssue, ...],
        default_target_branch: str = "main",
    ) -> list[FixPlanProposal]:
        """Process multiple candidate issues and generate plan proposals for open ones."""
        proposals: list[FixPlanProposal] = []
        for issue in issues:
            if issue.status == IssueResolutionStatus.OPEN:
                proposals.append(self.generate_proposal(issue, default_target_branch))
        return proposals

    def render_proposals_markdown(
        self, proposals: list[FixPlanProposal] | tuple[FixPlanProposal, ...]
    ) -> str:
        """Render markdown triage table allowing users to select tasks to dispatch."""
        lines: list[str] = [
            "### 🛠️ 待修 Issue 自动化分析与修复建议",
            "已完成待修 Issue 复杂度评估与影响范围分析，请勾选确认执行的修复提案：",
            "",
            "| Issue | 仓库 | 预估风险 | 置信度 | 涉及关键文件 | 建议修复方案 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for p in proposals:
            files_str = "<br>".join(p.affected_files[:2])
            if len(p.affected_files) > 2:
                files_str += f"<br>... (+{len(p.affected_files) - 2})"

            lines.append(
                f"| `#{p.issue_id}` | `{p.repo}` | **{p.estimated_risk}** | {int(p.automated_confidence * 100)}% | `{files_str}` | {p.plan_summary} |"
            )

        return "\n".join(lines)
