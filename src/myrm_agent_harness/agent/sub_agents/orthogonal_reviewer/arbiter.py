from myrm_agent_harness.agent.sub_agents.orthogonal_reviewer.blind_reviewer import (
    BlindCleanContextReviewer,
)
from myrm_agent_harness.agent.sub_agents.orthogonal_reviewer.intent_reviewer import (
    IntentAlignmentReviewer,
)
from myrm_agent_harness.agent.sub_agents.orthogonal_reviewer.types import (
    ArbitrationStatus,
    ArbitrationVerdict,
    FindingCategory,
    FindingSeverity,
    ReviewFinding,
    ReviewerReport,
)


class OrthogonalReviewArbiter:
    """Arbiter synthesizing dual orthogonal reviewer findings into a unified verdict.

    Deduplicates semantic findings between Intent Reviewer A and Blind Reviewer B,
    evaluates blocking gate thresholds, and produces targeted auto-fix prompts.
    """

    def __init__(self) -> None:
        self.intent_reviewer = IntentAlignmentReviewer()
        self.blind_reviewer = BlindCleanContextReviewer()

    def arbitrate(
        self,
        session_id: str,
        report_a: ReviewerReport,
        report_b: ReviewerReport,
    ) -> ArbitrationVerdict:
        raw_findings: list[ReviewFinding] = []
        raw_findings.extend(report_a.findings)
        raw_findings.extend(report_b.findings)

        # Deduplicate findings with same file and category
        deduplicated: list[ReviewFinding] = []
        seen_keys: set[str] = set()
        dedup_counter = 0

        for f in raw_findings:
            key = f"{f.file_path}:{f.category}:{f.title}"
            if key in seen_keys:
                dedup_counter += 1
                # Upgrade existing severity if current is higher
                for existing in deduplicated:
                    if f"{existing.file_path}:{existing.category}:{existing.title}" == key:
                        if f.severity == FindingSeverity.CRITICAL and existing.severity != FindingSeverity.CRITICAL:
                            existing.severity = FindingSeverity.CRITICAL
                            existing.description += f" [交叉确认: {f.description}]"
                continue
            seen_keys.add(key)
            deduplicated.append(f)

        # Compute max severity
        max_severity: FindingSeverity | None = None
        if any(f.severity == FindingSeverity.CRITICAL for f in deduplicated):
            max_severity = FindingSeverity.CRITICAL
        elif any(f.severity == FindingSeverity.WARNING for f in deduplicated):
            max_severity = FindingSeverity.WARNING
        elif any(f.severity == FindingSeverity.INFO for f in deduplicated):
            max_severity = FindingSeverity.INFO

        # Determine status and approval
        auto_fix_prompts: list[str] = []
        if max_severity == FindingSeverity.CRITICAL:
            is_approved = False
            # Check if escalation is required
            has_intent_drift = any(f.category == FindingCategory.INTENT_DRIFT for f in deduplicated)
            has_breaking_change = any(f.category == FindingCategory.REGRESSION_RISK for f in deduplicated)
            if has_intent_drift or has_breaking_change:
                status = ArbitrationStatus.BLOCKED_MANUAL_ESCALATION
            else:
                status = ArbitrationStatus.BLOCKED_AUTO_FIX

            for f in deduplicated:
                if f.severity in (FindingSeverity.CRITICAL, FindingSeverity.WARNING):
                    prompt_snippet = (
                        f"修复缺陷 [{f.category}]: {f.title}。\n"
                        f"文件: {f.file_path} {f.line_range}\n"
                        f"原因: {f.description}\n"
                        f"指引: {f.suggestion}"
                    )
                    auto_fix_prompts.append(prompt_snippet)
        else:
            is_approved = True
            status = ArbitrationStatus.APPROVED

        summary = (
            f"正交双审仲裁完成: 综合评定={status.value.upper()}, 准入放行={is_approved}, "
            f"合并缺陷数={len(deduplicated)} (去重 {dedup_counter} 项)。"
        )

        return ArbitrationVerdict(
            session_id=session_id,
            is_approved=is_approved,
            status=status,
            max_severity=max_severity,
            merged_findings=deduplicated,
            deduplicated_count=dedup_counter,
            auto_fix_prompts=auto_fix_prompts,
            summary=summary,
        )

    def conduct_full_review(
        self,
        session_id: str,
        task_prompt: str,
        architecture_plan: str,
        code_diff: str,
        files_touched: list[str],
        public_signatures: list[str] | None = None,
    ) -> tuple[ReviewerReport, ReviewerReport, ArbitrationVerdict]:
        report_a = self.intent_reviewer.review(
            task_prompt=task_prompt,
            architecture_plan=architecture_plan,
            code_diff=code_diff,
            files_touched=files_touched,
        )
        report_b = self.blind_reviewer.review(
            code_diff=code_diff,
            files_touched=files_touched,
            public_signatures=public_signatures,
        )
        verdict = self.arbitrate(
            session_id=session_id,
            report_a=report_a,
            report_b=report_b,
        )
        return report_a, report_b, verdict
