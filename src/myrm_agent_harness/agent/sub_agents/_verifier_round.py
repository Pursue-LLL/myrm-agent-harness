"""Single-round verifier spawn and verify_worker_output entry point.

[INPUT]
- agent.sub_agents._verification_parsing::VerificationVerdict, _parse_verdict, _emit_verification_verdict
- agent.sub_agents._workspace_diff::take_workspace_snapshot, diff_snapshots
- agent.sub_agents.types::SubagentConfig, SubAgentResult, SubAgentStatus
- toolkits.code_execution.executors (POS: ReadonlyExecutorProxy for verifier sandbox)

[OUTPUT]
- verify_worker_output: Verify existing worker output without re-running worker
- _execute_verifier_round: Internal single-round verifier spawn

[POS]
Verifier-only round execution used by Cron post-run delivery assurance and orchestration.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents._verification_parsing import (
    VerificationVerdict,
    _emit_verification_verdict,
    _parse_verdict,
)
from myrm_agent_harness.agent.sub_agents._workspace_diff import (
    diff_snapshots,
    take_workspace_snapshot,
)
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from .manager import SubagentManager

logger = get_agent_logger(__name__)

__all__ = ["verify_worker_output"]


def _build_verifier_tool_registry_getter(
    tool_registry_getter: Callable[[], list[BaseTool]],
    context: dict[str, object],
) -> Callable[[], list[BaseTool]]:
    def verifier_tool_registry_getter() -> list[BaseTool]:
        base_tools = tool_registry_getter()
        safe_tools = []
        for t in base_tools:
            is_readonly = getattr(t, "readonly", None)
            if is_readonly is None:
                metadata = getattr(t, "metadata", {}) or {}
                is_readonly = metadata.get("readonly", None)

            is_mcp = getattr(t, "is_mcp", False) or (getattr(t, "metadata", {}) or {}).get("is_mcp", False)
            if is_mcp and not is_readonly:
                continue

            safe_tools.append(t)

        from myrm_agent_harness.agent.orchestration.signals.verifier import create_submit_verdict_tool

        safe_tools.append(create_submit_verdict_tool(context))
        return safe_tools

    return verifier_tool_registry_getter


async def _execute_verifier_round(
    manager: SubagentManager,
    *,
    worker_output: str,
    worker_type: str,
    verifier_type: str,
    verifier_config: SubagentConfig,
    context: dict[str, object],
    tool_registry_getter: Callable[[], list[BaseTool]],
    round_num: int,
    max_rounds: int,
    verifier_task_template: str = "",
    pre_snapshot: dict[str, tuple[float, int]] | None = None,
) -> VerificationVerdict | None:
    """Spawn a verifier subagent for an existing worker output and return the parsed verdict."""
    from myrm_agent_harness.agent.skills.evolution.execution.executor_context import (
        ExecutorContextManager,
    )
    from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy
    from myrm_agent_harness.toolkits.code_execution.executors.base import (
        get_executor,
    )
    from myrm_agent_harness.toolkits.code_execution.executors.readonly_proxy import (
        ReadonlyExecutorProxy,
    )

    verifier_task_id = f"verify-check-{round_num}-{verifier_type}"
    workspace_path = context.get("workspace_path")

    workspace_diff = ""
    if pre_snapshot and workspace_path and isinstance(workspace_path, str):
        try:
            post_snapshot = take_workspace_snapshot(workspace_path)
            workspace_diff = diff_snapshots(pre_snapshot, post_snapshot)
        except Exception as exc:
            logger.debug("[verification] Post-snapshot diff failed: %s", exc)

    base_desc = (
        "You are an Adversarial Sandbox Verifier.\n"
        "Verify the following work output by strictly applying your verification protocol.\n\n"
        "CRITICAL RULES:\n"
        "1. Do NOT just read the code and guess if it works. You MUST write and execute test scripts "
        "(via run_bash or python_execute) or run curl/ping to physically verify the output.\n"
        "2. You MUST include the actual execution logs (STDOUT/STDERR) from your tests in your final response.\n"
        "3. A 'PASS' verdict without execution evidence will be REJECTED by the system. "
        "The system tracks your execution at the OS level, so you cannot fake it by just writing 'STDOUT'.\n\n"
    )

    if workspace_diff:
        base_desc += (
            f"{workspace_diff}\n\n"
            "IMPORTANT: Review ALL files listed above, not just those mentioned in the Worker Output. "
            "Files modified but not reported by the worker may contain unintended side effects.\n\n"
        )

    if verifier_task_template:
        if "{worker_result}" in verifier_task_template:
            verifier_task_desc = base_desc + verifier_task_template.replace("{worker_result}", worker_output)
        else:
            verifier_task_desc = (
                base_desc
                + f"SPECIFIC VERIFICATION CRITERIA:\n{verifier_task_template}\n\n## Worker Output\n\n{worker_output}"
            )
    else:
        verifier_task_desc = base_desc + f"## Worker Output\n\n{worker_output}"

    round_verifier_config = dataclasses.replace(
        verifier_config,
        description=f"\u72ec\u7acb\u5ba1\u67e5\u4e2d... [\u8f6e\u6b21 {round_num}/{max_rounds}]",
        display_name=f"Adversarial Verifier ({round_num}/{max_rounds})",
    )

    logger.info(
        "[verification] Round %d/%d — spawning verifier '%s'",
        round_num,
        max_rounds,
        verifier_type,
    )

    verifier_tool_registry_getter = _build_verifier_tool_registry_getter(tool_registry_getter, context)

    current_executor = get_executor()
    use_readonly = round_verifier_config.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX

    if current_executor:
        proxy_executor = ReadonlyExecutorProxy(current_executor) if use_readonly else None
        ctx_mgr = ExecutorContextManager(proxy_executor) if proxy_executor else None
        if ctx_mgr:
            with ctx_mgr:
                verifier_result = await manager.spawn_child(
                    task_id=verifier_task_id,
                    agent_type=verifier_type,
                    task_description=verifier_task_desc,
                    config=round_verifier_config,
                    context=context,
                    tool_registry_getter=verifier_tool_registry_getter,
                    wait=True,
                )
        else:
            verifier_result = await manager.spawn_child(
                task_id=verifier_task_id,
                agent_type=verifier_type,
                task_description=verifier_task_desc,
                config=round_verifier_config,
                context=context,
                tool_registry_getter=verifier_tool_registry_getter,
                wait=True,
            )
        tracked_executor = proxy_executor or current_executor
        context["_verifier_has_executed_code"] = getattr(tracked_executor, "has_executed_code", False)
    else:
        if use_readonly:
            logger.warning("[verification] No current executor found, cannot apply READ_ONLY_SANDBOX")
        verifier_result = await manager.spawn_child(
            task_id=verifier_task_id,
            agent_type=verifier_type,
            task_description=verifier_task_desc,
            config=round_verifier_config,
            context=context,
            tool_registry_getter=verifier_tool_registry_getter,
            wait=True,
        )

    if isinstance(verifier_result, dict):
        verifier_result = SubAgentResult(
            success=bool(verifier_result.get("success", False)),
            task_id=verifier_task_id,
            agent_type=verifier_type,
            result=str(verifier_result.get("result", "")),
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
        )

    if not verifier_result.success:
        logger.warning(
            "[verification] Round %d — verifier failed: %s",
            round_num,
            verifier_result.error,
        )
        return None

    verdict = context.get("_verifier_verdict")
    if isinstance(verdict, VerificationVerdict):
        logger.info(
            "[verification] Round %d — Tool Calling Verdict=%s confidence=%s summary=%s",
            round_num,
            "PASS" if verdict.passed else "FAIL",
            verdict.confidence,
            verdict.summary,
        )
    else:
        verdict = _parse_verdict(verifier_result.result)
        logger.info(
            "[verification] Round %d — Regex Verdict=%s confidence=%s summary=%s",
            round_num,
            "PASS" if verdict.passed else "FAIL",
            verdict.confidence,
            verdict.summary,
        )

    has_executed = context.get("_verifier_has_executed_code", False)
    if verdict.passed and not has_executed:
        logger.warning(
            "[verification] Round %d — Verifier granted PASS but did not execute any code. Rejecting verdict.",
            round_num,
        )
        msg = (
            "FAIL: Validation rejected. System detected that you did not execute any code. "
            "You MUST use bash or python tools to run tests and observe actual STDOUT/STDERR "
            "before granting a PASS."
        )
        verdict = dataclasses.replace(
            verdict,
            passed=False,
            summary=msg,
            raw=f"{verdict.raw}\n\n{msg}",
        )

    context.pop("_verifier_verdict", None)
    context.pop("_verifier_has_executed_code", None)

    await _emit_verification_verdict(
        verdict=verdict,
        round_num=round_num,
        max_rounds=max_rounds,
        worker_type=worker_type,
        verifier_type=verifier_type,
        has_diff=bool(workspace_diff),
    )

    return verdict


async def verify_worker_output(
    manager: SubagentManager,
    *,
    worker_output: str,
    worker_type: str,
    verifier_type: str,
    verifier_config: SubagentConfig,
    context: dict[str, object],
    tool_registry_getter: Callable[[], list[BaseTool]],
    verifier_task_template: str = "",
) -> VerificationVerdict:
    """Verify an existing worker output without re-running the worker."""
    verdict = await _execute_verifier_round(
        manager,
        worker_output=worker_output,
        worker_type=worker_type,
        verifier_type=verifier_type,
        verifier_config=verifier_config,
        context=context,
        tool_registry_getter=tool_registry_getter,
        round_num=1,
        max_rounds=1,
        verifier_task_template=verifier_task_template,
    )
    if verdict is None:
        return VerificationVerdict(
            passed=False,
            summary="Verifier subagent failed to complete",
            confidence="LOW",
            findings=[],
            raw="",
        )
    return verdict
