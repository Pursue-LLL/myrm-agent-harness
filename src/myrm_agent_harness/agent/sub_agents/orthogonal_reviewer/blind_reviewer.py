import re
import time
import uuid

from myrm_agent_harness.agent.sub_agents.orthogonal_reviewer.types import (
    FindingCategory,
    FindingSeverity,
    ReviewFinding,
    ReviewerPerspective,
    ReviewerReport,
)


class BlindCleanContextReviewer:
    """Reviewer B: Pure clean-context blind reviewer, free from prior CoT confirmation bias.

    Inspects code purely based on diffs, public contracts, and syntax/type semantics.
    Specializes in finding unhandled edge cases, Any types, regression risks, and safety gaps.
    """

    def review(
        self,
        code_diff: str,
        files_touched: list[str],
        public_signatures: list[str] | None = None,
    ) -> ReviewerReport:
        start_time = time.perf_counter()
        findings: list[ReviewFinding] = []

        diff_lines = code_diff.splitlines()

        # Check 1: Any type prohibition (Critical violation of code quality guidelines)
        any_type_pattern = re.compile(r":\s*Any\b|->\s*Any\b|\[Any\]")
        for i, line in enumerate(diff_lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("+") and not stripped.startswith("+++"):
                if any_type_pattern.search(stripped):
                    findings.append(
                        ReviewFinding(
                            finding_id=f"blind-{uuid.uuid4().hex[:8]}",
                            reviewer=ReviewerPerspective.BLIND_CLEAN_CONTEXT,
                            severity=FindingSeverity.CRITICAL,
                            category=FindingCategory.TYPE_SAFETY,
                            title="检测到严禁的 Any 类型 (Any Type Prohibited)",
                            description="新增代码中包含 Any 类型注解，违反项目严格类型红线，可能掩盖隐性类型错误。",
                            file_path=files_touched[0] if files_touched else "unknown",
                            line_range=f"Diff +L{i}",
                            suggestion="必须替换为具体的 Pydantic 模型、泛型类型、Union 或具体的 Type Hints。",
                        )
                    )

        # Check 2: Potential unhandled zero division or empty container indexing
        zero_div_pattern = re.compile(r"/\s*(len\(|\w+\.count|\b0\b)")
        empty_index_pattern = re.compile(r"\[0\]|\.pop\(0\)")
        for i, line in enumerate(diff_lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("+") and not stripped.startswith("+++"):
                if zero_div_pattern.search(stripped) and "if" not in stripped and "max(1," not in stripped:
                    findings.append(
                        ReviewFinding(
                            finding_id=f"blind-{uuid.uuid4().hex[:8]}",
                            reviewer=ReviewerPerspective.BLIND_CLEAN_CONTEXT,
                            severity=FindingSeverity.WARNING,
                            category=FindingCategory.BOUNDARY_EDGE_CASE,
                            title="潜在零除异常边界 (Potential Zero Division)",
                            description="除法运算未见显式判空或 max(1, denominator) 保护，容器为空时可能触发 ZeroDivisionError。",
                            file_path=files_touched[0] if files_touched else "unknown",
                            line_range=f"Diff +L{i}",
                            suggestion="使用 max(1, denominator) 或在运算前增加条件守卫。",
                        )
                    )
                if empty_index_pattern.search(stripped) and "if" not in stripped and "default" not in stripped:
                    findings.append(
                        ReviewFinding(
                            finding_id=f"blind-{uuid.uuid4().hex[:8]}",
                            reviewer=ReviewerPerspective.BLIND_CLEAN_CONTEXT,
                            severity=FindingSeverity.INFO,
                            category=FindingCategory.BOUNDARY_EDGE_CASE,
                            title="直接索引首元素风险 (Unchecked Head Indexing)",
                            description="直接对列表下标 [0] 访问，如果输入为空序列将引发 IndexError。",
                            file_path=files_touched[0] if files_touched else "unknown",
                            line_range=f"Diff +L{i}",
                            suggestion="优先使用 next(iter(...), None) 或在取下标前检查列表长度非空。",
                        )
                    )

        # Check 3: Check breaking change in public contract signatures
        if public_signatures:
            for sig in public_signatures:
                # If a public method signature is deleted in diff
                deleted_sig_pattern = f"-def {sig}"
                if any(deleted_sig_pattern in line.lstrip() for line in diff_lines):
                    findings.append(
                        ReviewFinding(
                            finding_id=f"blind-{uuid.uuid4().hex[:8]}",
                            reviewer=ReviewerPerspective.BLIND_CLEAN_CONTEXT,
                            severity=FindingSeverity.CRITICAL,
                            category=FindingCategory.REGRESSION_RISK,
                            title="公共接口破坏性回归风险 (Breaking Signature Change)",
                            description=f"公共方法签名 '{sig}' 在差异中被删除或修改，破坏了既有 API 契约。",
                            file_path=files_touched[0] if files_touched else "unknown",
                            line_range="",
                            suggestion="保持公共契约签名向后兼容或通过重载提供过渡期支持。",
                        )
                    )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        has_critical = any(f.severity == FindingSeverity.CRITICAL for f in findings)
        passed = not has_critical

        summary = (
            f"视角 B（全新盲态零偏见）审查完毕：共发现 {len(findings)} 处问题 "
            f"({len([f for f in findings if f.severity == FindingSeverity.CRITICAL])} 处阻塞级)。"
        )

        return ReviewerReport(
            perspective=ReviewerPerspective.BLIND_CLEAN_CONTEXT,
            findings=findings,
            passed=passed,
            summary=summary,
            execution_time_ms=elapsed_ms,
        )
