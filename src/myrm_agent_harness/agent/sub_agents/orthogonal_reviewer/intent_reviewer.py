import time
import uuid

from myrm_agent_harness.agent.sub_agents.orthogonal_reviewer.types import (
    FindingCategory,
    FindingSeverity,
    ReviewFinding,
    ReviewerPerspective,
    ReviewerReport,
)


class IntentAlignmentReviewer:
    """Reviewer A: Evaluates code changes with shared context, intent, and architectural goals.

    Specializes in detecting intent drift, unfulfilled business logic,
    and unprompted over-engineering.
    """

    def review(
        self,
        task_prompt: str,
        architecture_plan: str,
        code_diff: str,
        files_touched: list[str],
    ) -> ReviewerReport:
        start_time = time.perf_counter()
        findings: list[ReviewFinding] = []

        cleaned_prompt = task_prompt.strip().lower()
        cleaned_plan = architecture_plan.strip().lower()
        cleaned_diff = code_diff.strip().lower()

        # Heuristic 1: Intent drift check - check required keywords in prompt vs diff
        if "must have" in cleaned_prompt or "必须" in task_prompt:
            # Check if critical features mentioned in prompt are missing in diff
            prompt_requirements = [
                line.strip()
                for line in task_prompt.splitlines()
                if "必须" in line or "must" in line.lower()
            ]
            for req in prompt_requirements:
                req_core = req.replace("必须", "").replace("must", "").strip()
                if len(req_core) > 4 and req_core.lower() not in cleaned_diff:
                    findings.append(
                        ReviewFinding(
                            finding_id=f"intent-{uuid.uuid4().hex[:8]}",
                            reviewer=ReviewerPerspective.INTENT_ALIGNMENT,
                            severity=FindingSeverity.CRITICAL,
                            category=FindingCategory.INTENT_DRIFT,
                            title="核心业务意图缺失 (Intent Drift)",
                            description=f"原始需求明确要求: '{req}'，但在提交的差异中未检索到对应实现。",
                            file_path=files_touched[0] if files_touched else "unknown",
                            line_range="",
                            suggestion=f"请对照需求补齐关键逻辑: '{req_core}'。",
                        )
                    )

        # Heuristic 2: Over-engineering check - touched unexpected modules or introduced complex unrequested abstractions
        if len(files_touched) > 10 and ("simple" in cleaned_prompt or "简单" in task_prompt):
            findings.append(
                ReviewFinding(
                    finding_id=f"intent-{uuid.uuid4().hex[:8]}",
                    reviewer=ReviewerPerspective.INTENT_ALIGNMENT,
                    severity=FindingSeverity.WARNING,
                    category=FindingCategory.OVER_ENGINEERING,
                    title="过度设计与范围蔓延 (Over-Engineering)",
                    description="简单任务触及了超过 10 个独立文件，引入了非必要的全局侵入或过早抽象。",
                    file_path=files_touched[0] if files_touched else "unknown",
                    line_range="",
                    suggestion="收敛改动范围，遵循单一职责与最少特权原则，移除冗余包装层。",
                )
            )

        # Heuristic 3: Check architectural alignment with plan
        if cleaned_plan and "schema" in cleaned_plan and "schema" not in cleaned_diff and not any("schema" in f.lower() for f in files_touched):
            findings.append(
                ReviewFinding(
                    finding_id=f"intent-{uuid.uuid4().hex[:8]}",
                    reviewer=ReviewerPerspective.INTENT_ALIGNMENT,
                    severity=FindingSeverity.WARNING,
                    category=FindingCategory.LOGIC_FLAW,
                    title="架构规划契约未落地 (Unfulfilled Plan Contract)",
                    description="架构规划明确定义了 Schema/DTO 约束，但未见相关 Schema 文件增改。",
                    file_path=files_touched[0] if files_touched else "unknown",
                    line_range="",
                    suggestion="在对应 schemas 模块补齐强类型 DTO 声明并严格排除 Any 类型。",
                )
            )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        has_critical = any(f.severity == FindingSeverity.CRITICAL for f in findings)
        passed = not has_critical

        summary = (
            f"视角 A（意图与架构一致性）审查完毕：共发现 {len(findings)} 处问题 "
            f"({len([f for f in findings if f.severity == FindingSeverity.CRITICAL])} 处阻塞级)。"
        )

        return ReviewerReport(
            perspective=ReviewerPerspective.INTENT_ALIGNMENT,
            findings=findings,
            passed=passed,
            summary=summary,
            execution_time_ms=elapsed_ms,
        )
