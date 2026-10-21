"""Morning and evening engineering digest engine and card renderer.

Faithfully implements Today Huajuan's engineering digest paradigm:
- Morning Brief (08:30): Summarizes today's agenda, overnight automated sandbox deliverables,
  and pull requests awaiting human review/merge.
- Evening Brief (20:30): Consolidates daily completion metrics, resolved issues across projects,
  unresolved risks, and recommended resumption tasks for tomorrow.
- Renders GitHub Flavored Markdown briefing cards and structured JSON dictionaries.

[OUTPUT]
- EngineeringDigestEngine: Aggregates project activity and formats panoramic briefs.

[INPUT]
- __future__
- time
- uuid

[OUTPUT]
- EngineeringDigestEngine

[POS]
Morning and evening engineering digest engine and card renderer.
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.runtime.issue_resolution.pipeline_types import (
    DigestKind,
    EngineeringDigest,
    PullRequestPayload,
    RepositoryIssue,
)


class EngineeringDigestEngine:
    """Compiles panoramic engineering briefs across tracked codebases."""

    def generate_morning_brief(
        self,
        projects_monitored: list[str] | tuple[str, ...],
        pending_merge_prs: list[PullRequestPayload] | tuple[PullRequestPayload, ...],
        upcoming_tasks: list[str] | tuple[str, ...],
        open_risks: list[str] | tuple[str, ...] = (),
    ) -> EngineeringDigest:
        """Construct the morning engineering brief focusing on agenda and pending PRs."""
        return EngineeringDigest(
            digest_id=f"digest_morn_{uuid.uuid4().hex[:8]}",
            kind=DigestKind.MORNING_BRIEF,
            timestamp=time.time(),
            projects_monitored=tuple(projects_monitored),
            pending_merge_prs=tuple(pending_merge_prs),
            resolved_issues=(),
            upcoming_tasks=tuple(upcoming_tasks),
            open_risks=tuple(open_risks),
        )

    def generate_evening_brief(
        self,
        projects_monitored: list[str] | tuple[str, ...],
        resolved_issues: list[RepositoryIssue] | tuple[RepositoryIssue, ...],
        pending_merge_prs: list[PullRequestPayload] | tuple[PullRequestPayload, ...],
        open_risks: list[str] | tuple[str, ...] = (),
        tomorrow_tasks: list[str] | tuple[str, ...] = (),
    ) -> EngineeringDigest:
        """Construct the evening engineering brief consolidating daily accomplishments and risks."""
        return EngineeringDigest(
            digest_id=f"digest_eve_{uuid.uuid4().hex[:8]}",
            kind=DigestKind.EVENING_BRIEF,
            timestamp=time.time(),
            projects_monitored=tuple(projects_monitored),
            pending_merge_prs=tuple(pending_merge_prs),
            resolved_issues=tuple(resolved_issues),
            upcoming_tasks=tuple(tomorrow_tasks),
            open_risks=tuple(open_risks),
        )

    def render_markdown_brief(self, digest: EngineeringDigest) -> str:
        """Render a GitHub Flavored Markdown panoramic briefing card."""
        is_morning = digest.kind == DigestKind.MORNING_BRIEF
        title_prefix = "☀️ 晨间工程简报 (Morning Brief)" if is_morning else "🌙 晚间工程复盘 (Evening Brief)"

        lines: list[str] = [
            f"### {title_prefix}",
            f"- **简报编号**: `{digest.digest_id}`",
            f"- **监控项目**: {', '.join(f'`{p}`' for p in digest.projects_monitored) if digest.projects_monitored else '无'}",
            f"- **待合并 PR 数量**: `{len(digest.pending_merge_prs)}`",
            f"- **今日解决 Issue 数量**: `{len(digest.resolved_issues)}`",
            "",
        ]

        # Section 1: Pending Merge Pull Requests
        if digest.pending_merge_prs:
            lines.extend(
                [
                    "#### 📥 待人工审查合并的 Pull Requests",
                    "| PR 编号 | 仓库 | 分支 | 关联 Issue | 标题 |",
                    "| :--- | :--- | :--- | :--- | :--- |",
                ]
            )
            for pr in digest.pending_merge_prs:
                lines.append(
                    f"| `#{pr.pr_id}` | `{pr.repo}` | `{pr.source_branch}` ➔ `{pr.target_branch}` | `#{pr.related_issue_id}` | {pr.title} |"
                )
            lines.append("")

        # Section 2: Resolved Issues (primarily evening)
        if digest.resolved_issues:
            lines.extend(
                [
                    "#### ✅ 已闭环解决的 Issues",
                    "| Issue | 仓库 | 优先级 | 标题 |",
                    "| :--- | :--- | :--- | :--- |",
                ]
            )
            for iss in digest.resolved_issues:
                lines.append(
                    f"| `#{iss.issue_id}` | `{iss.repo}` | {iss.priority.value.upper()} | {iss.title} |"
                )
            lines.append("")

        # Section 3: Tasks / Agenda
        task_heading = "#### 📋 今日重点排期计划" if is_morning else "#### 📌 明日续跑与待办建议"
        if digest.upcoming_tasks:
            lines.append(task_heading)
            for t in digest.upcoming_tasks:
                lines.append(f"- {t}")
            lines.append("")

        # Section 4: Risks
        if digest.open_risks:
            lines.extend(
                [
                    "> [!WARNING]",
                    "> **遗留未决风险提示**：",
                ]
            )
            for r in digest.open_risks:
                lines.append(f"> - {r}")
            lines.append("")

        return "\n".join(lines)

    def render_json_summary(self, digest: EngineeringDigest) -> dict[str, object]:
        """Export typed dictionary for frontend UI digest components."""
        return {
            "digest_id": digest.digest_id,
            "kind": digest.kind.value,
            "timestamp": digest.timestamp,
            "projects_monitored": list(digest.projects_monitored),
            "pending_prs_count": len(digest.pending_merge_prs),
            "pending_prs": [
                {
                    "pr_id": pr.pr_id,
                    "repo": pr.repo,
                    "source_branch": pr.source_branch,
                    "target_branch": pr.target_branch,
                    "title": pr.title,
                    "related_issue_id": pr.related_issue_id,
                }
                for pr in digest.pending_merge_prs
            ],
            "resolved_issues_count": len(digest.resolved_issues),
            "resolved_issues": [
                {
                    "issue_id": iss.issue_id,
                    "repo": iss.repo,
                    "priority": iss.priority.value,
                    "title": iss.title,
                }
                for iss in digest.resolved_issues
            ],
            "upcoming_tasks": list(digest.upcoming_tasks),
            "open_risks": list(digest.open_risks),
        }
