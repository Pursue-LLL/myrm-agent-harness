"""
[INPUT]
- myrm_agent_harness.agent.sub_agents.ralph_loop.types (RalphHandoffReport, RalphLoopConfig)

[OUTPUT]
- sanitize_handoff_report: 校验清洗五字段交接报告与容量硬顶控制
- evaluate_blocked_guardrail: 尝试满三轮阻断防御规则评估与降级
- compose_fresh_agent_directive: 装配下一轮无历史 Fresh 子 Agent 的满血根提示词

[POS]
Harness 框架层 Ralph 式 Fresh-Agent 强交接协议与阻断门禁规则执行器（Topic 12 · 第 15 项）。
落实 DSH Ralph 模式五字段强契约、min-3-round 规则与满血零对话 seed 指令拼装。
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.ralph_loop.types import (
    RalphHandoffReport,
    RalphLoopConfig,
)


def sanitize_handoff_report(
    report: RalphHandoffReport,
    config: RalphLoopConfig,
) -> RalphHandoffReport:
    """
    对五字段交接报告进行清洗与容量硬顶控制。
    若总字符数超过 max_handoff_chars，按比例保护重要字段并截断多余字符。
    """
    total = report.total_chars()
    if total <= config.max_handoff_chars:
        return report

    # 容量超限时，优先保证 status 和 blocker，对 summary 与 next_steps 进行安全截断
    max_text_len = (config.max_handoff_chars - 200) // 2
    truncated_summary = (
        report.summary[:max_text_len] + " ...[truncated]"
        if len(report.summary) > max_text_len
        else report.summary
    )
    truncated_next_steps = (
        report.next_steps[:max_text_len] + " ...[truncated]"
        if len(report.next_steps) > max_text_len
        else report.next_steps
    )
    truncated_evidence = (
        report.evidence[:200] + " ...[truncated]"
        if len(report.evidence) > 200
        else report.evidence
    )

    return RalphHandoffReport(
        status=report.status,
        summary=truncated_summary,
        evidence=truncated_evidence,
        next_steps=truncated_next_steps,
        blocker=report.blocker,
    )


def evaluate_blocked_guardrail(
    report: RalphHandoffReport,
    round_index: int,
    config: RalphLoopConfig,
) -> tuple[RalphHandoffReport, bool]:
    """
    评估至少尝试满三轮阻断防御规则 (Min-3-Round Rule)。
    如果子 Agent 在未满 min_rounds_before_blocked 轮次时声称 blocked，
    强制降级为 in_progress，并在 next_steps 注入警示与备选策略重试指引。

    Returns:
        (sanitized_report, was_downgraded)
    """
    if report.status != "blocked":
        return report, False

    if round_index >= config.min_rounds_before_blocked:
        # 已满最小轮次门槛，合规接受 blocked 状态
        return report, False

    # 触发降级
    guardrail_note = (
        f"\n[Ralph Guardrail] 至少需尝试满 {config.min_rounds_before_blocked} 轮才能声明 BLOCKED。"
        f"当前仅为第 {round_index} 轮，已强制恢复为 IN_PROGRESS。"
        f"请在下轮调整替代方案、查阅工作区文件或执行诊断以继续推进。"
        f"原阻塞成因: {report.blocker or '未指明'}"
    )

    downgraded_report = RalphHandoffReport(
        status="in_progress",
        summary=report.summary,
        evidence=report.evidence,
        next_steps=f"{report.next_steps}{guardrail_note}",
        blocker=report.blocker,
    )
    return downgraded_report, True


def compose_fresh_agent_directive(
    human_goal: str,
    workspace_root: str,
    round_index: int,
    max_rounds: int,
    prior_handoff: RalphHandoffReport | None = None,
) -> str:
    """
    为新一轮 Fresh 子 Agent 装配满血零历史指令。
    不携带前序会话的冗长消息历史，仅注入人类根本目标、共享工作区位置与上一轮交接五字段。
    """
    lines: list[str] = [
        "=== RALPH FRESH AGENT ROUND DIRECTIVE ===",
        f"Round: {round_index} / {max_rounds}",
        "Context Status: FRESH (无前置对话历史，满血全新推理)",
        f"Shared Workspace: {workspace_root}",
        "",
        "--- [IMMUTABLE] Human Goal ---",
        human_goal.strip(),
        "",
    ]

    if prior_handoff is not None:
        lines.extend([
            "--- Prior Round Handoff (Structured 5-Field) ---",
            f"Status: {prior_handoff.status.upper()}",
            f"Summary: {prior_handoff.summary.strip()}",
            f"Evidence: {prior_handoff.evidence.strip()}",
            f"Next Steps Directive: {prior_handoff.next_steps.strip()}",
        ])
        if prior_handoff.blocker:
            lines.append(f"Reported Blocker: {prior_handoff.blocker.strip()}")
        lines.append("")

    lines.extend([
        "--- Execution Protocol ---",
        "1. 工作区优先：所有代码、产物与测试状态请直接在共享工作区中读写与验证。",
        "2. 轮次终了交接：在完成本轮工作后，输出结构化五字段报告 (status, summary, evidence, next_steps, blocker)。",
        "3. 阻断规则：未满 3 轮严禁声明 blocked，必须至少尝试 3 次替代方案。",
        "============================================",
    ])

    return "\n".join(lines)
