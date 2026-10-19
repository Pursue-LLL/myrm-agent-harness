"""The ``_completion_check`` runtime hook injected by the CompletionGuard.

The guard rewrites the agent's completion attempt into a call of this tool when
critical verification problems are found. The returned text is model-facing: it
names the blocking reason and the two acceptable fixes (produce the evidence, or
state exactly what was not done). The final fallback returns the task-aware
verification checklist built from this run's tool records.

Keeping the tool separate from the guard orchestration keeps both files focused:
the guard decides *whether* to block, this module decides *what the model reads*.

[INPUT]
- agent.middlewares.completion.completion_guard_checklist::build_checklist (POS: 任务感知验证清单)
- agent.orchestration.hooks::COMPLETION_CHECK_TOOL_NAME (POS: 运行时钩子名 SSOT)

[OUTPUT]
- _completion_check_tool: 完成检查运行时钩子，按阻断原因返回模型侧指令，无原因时返回验证清单

[POS]
CompletionGuard 注入的完成检查钩子。模型可见文案的唯一定义处：每种阻断原因对应一条可执行修复指引。
"""

from __future__ import annotations

from langchain_core.tools import tool

from myrm_agent_harness.agent.middlewares.completion.completion_guard_checklist import (
    build_checklist,
)
from myrm_agent_harness.agent.orchestration.hooks import COMPLETION_CHECK_TOOL_NAME


@tool(COMPLETION_CHECK_TOOL_NAME)
def _completion_check_tool(
    workspace_root: str = "",
    force_fail: bool = False,
    evidence_reason: str = "",
    deliverable_write_reason: str = "",
    execution_claim_reason: str = "",
    query_grounding_reason: str = "",
    ppt_outline_reason: str = "",
    staged_artifacts: list[dict[str, object]] | None = None,
) -> str:
    """Generate a task-aware verification checklist before finishing.

    Review the session's tool-call history and produce a checklist of items
    to verify (tests, lint, type-check, browser state, execution results)
    before delivering the final answer.
    """
    if force_fail:
        msg = (
            " CRITICAL SYSTEM DIRECTIVE: You have failed to verify your work multiple times. "
            "You are now permitted to finish the task, but you MUST include a clear warning "
            "in your final response to the user stating that you were unable to successfully "
            "verify the changes (e.g., tests failed or were not run) and that they should "
            "manually review the work."
        )
        if staged_artifacts:
            staged_names = ", ".join(str(item.get("filename", "")) for item in staged_artifacts)
            msg += f"\nNOTICE: Unwritten deliverables were automatically staged to .myrm/staged_artifacts/ [{staged_names}]."
        if execution_claim_reason.strip():
            msg += (
                "\nNOTICE: Your draft claimed work that this run's execution record does not support. "
                "The warning in your final response must state that explicitly."
            )
        return msg

    if evidence_reason.strip():
        return (
            " CRITICAL COMPLETION CHECK: This response appears to require external evidence, "
            "but no successful evidence-gathering tools were observed in this run.\n"
            f"Reason: {evidence_reason}\n"
            "Before finishing, run at least one successful evidence step (web_search_tool, "
            "web_fetch_tool, browser evidence tools, or MCP tools), then synthesize the answer."
        )

    if deliverable_write_reason.strip():
        return (
            " CRITICAL COMPLETION CHECK: Deliverable write claim without tool evidence.\n"
            f"Reason: {deliverable_write_reason}\n"
            "Before finishing, call file_write_tool or file_edit_tool to persist the file, "
            "or revise the response to remove the false write claim."
        )

    if execution_claim_reason.strip():
        return (
            " CRITICAL COMPLETION CHECK: Completion claim without executed evidence.\n"
            f"Reason: {execution_claim_reason}\n"
            "Two acceptable fixes: (1) perform the action now so its tool result proves it, or "
            "(2) revise the response to state exactly what was done and what was not. "
            "Evidence proves an action ran; it does not by itself prove the result is correct."
        )

    if query_grounding_reason.strip():
        return (
            " CRITICAL COMPLETION CHECK: Entity query observation ungrounded.\n"
            f"Reason: {query_grounding_reason}\n"
            "Before finishing, execute the appropriate query or MCP tool to retrieve verified data, "
            "or revise the response to honestly state the missing status or tool failure to the user."
        )

    if ppt_outline_reason.strip():
        return (
            " CRITICAL COMPLETION CHECK: PPT Reporting Plan Outline Quality Gate Failed.\n"
            f"Reason: {ppt_outline_reason}\n"
            "Before delivering the final outline or executing slide generation, refine the presentation structure: "
            "ensure each slide has a punchy headline (max 6-8 words), an explicit takeaway statement, and concrete visual/data anchors."
        )

    from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import (
        get_loop_guard,
    )

    guard = get_loop_guard()
    records = list(guard._window)
    checklist_str, _ = build_checklist(records, workspace_root=workspace_root)
    return checklist_str


__all__ = ["_completion_check_tool"]
