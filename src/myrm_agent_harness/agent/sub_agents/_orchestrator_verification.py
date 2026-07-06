"""Adversarial verification orchestration for subagent outputs.

Worker -> Verifier -> Retry loop with structured verdict parsing.

[INPUT]
- agent.sub_agents.types::SubagentConfig, SubAgentResult, SubAgentStatus, WorkspacePolicy
- agent.sub_agents._workspace_diff::take_workspace_snapshot, diff_snapshots (POS: Workspace diff for adversarial verification)
- toolkits.code_execution (POS: executor proxies for sandboxed verification)
- core.events.types::AgentEventType (POS: Streaming event types — VERIFICATION_VERDICT)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: SSE event emission sink)

[OUTPUT]
- VerificationVerdict: Parsed verdict from a Verifier agent's structured JSON output.
- run_with_verification: Execute a worker then verify via adversarial verifier with workspace diff injection and verdict event emission.

[POS]
Adversarial verification orchestration — Worker -> Verifier -> Retry loop with workspace diff injection and structured verdict events.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents._verification_parsing import VerificationVerdict
from myrm_agent_harness.agent.sub_agents._verifier_round import (
    _execute_verifier_round,
    verify_worker_output,
)
from myrm_agent_harness.agent.sub_agents._workspace_diff import take_workspace_snapshot
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from .manager import SubagentManager

logger = get_agent_logger(__name__)

__all__ = ["VerificationVerdict", "run_with_verification", "verify_worker_output", "_parse_verdict"]


async def run_with_verification(
    manager: SubagentManager,
    worker_type: str,
    worker_config: SubagentConfig,
    worker_task: str,
    verifier_type: str,
    verifier_config: SubagentConfig,
    context: dict[str, object],
    tool_registry_getter: Callable[[], list[BaseTool]],
    max_rounds: int = 2,
    verifier_task_template: str = "",
) -> SubAgentResult:
    """Execute a worker then verify via an adversarial verifier, retrying on failure."""
    max_rounds = max(1, max_rounds)
    current_task = worker_task
    last_worker_result = SubAgentResult(
        success=False,
        task_id="verify-init",
        agent_type=worker_type,
        error="Verification not started",
        completed_at=time.time(),
        status=SubAgentStatus.FAILED,
    )
    verdict = None

    workspace_path = context.get("workspace_path")

    for round_idx in range(max_rounds):
        round_num = round_idx + 1
        worker_task_id = f"verify-worker-{round_num}-{worker_type}"

        logger.info(
            "[verification] Round %d/%d — spawning worker '%s'",
            round_num,
            max_rounds,
            worker_type,
        )

        pre_snapshot: dict[str, tuple[float, int]] = {}
        if workspace_path and isinstance(workspace_path, str):
            try:
                pre_snapshot = take_workspace_snapshot(workspace_path)
            except Exception as exc:
                logger.debug("[verification] Pre-snapshot failed: %s", exc)

        worker_result = await manager.spawn_child(
            task_id=worker_task_id,
            agent_type=worker_type,
            task_description=current_task,
            config=worker_config,
            context=context,
            tool_registry_getter=tool_registry_getter,
            wait=True,
        )
        if isinstance(worker_result, dict):
            worker_result = SubAgentResult(
                success=bool(worker_result.get("success", False)),
                task_id=worker_task_id,
                agent_type=worker_type,
                result=str(worker_result.get("result", "")),
                completed_at=time.time(),
                status=SubAgentStatus.COMPLETED,
            )
        last_worker_result = worker_result

        if not worker_result.success:
            logger.warning(
                "[verification] Round %d — worker failed: %s",
                round_num,
                worker_result.error,
            )
            break

        verdict = await _execute_verifier_round(
            manager,
            worker_output=worker_result.result,
            worker_type=worker_type,
            verifier_type=verifier_type,
            verifier_config=verifier_config,
            context=context,
            tool_registry_getter=tool_registry_getter,
            round_num=round_num,
            max_rounds=max_rounds,
            verifier_task_template=verifier_task_template,
            pre_snapshot=pre_snapshot,
        )

        if verdict is None:
            break

        if verdict.passed:
            last_worker_result.result = (
                f"{last_worker_result.result}\n\n"
                f"---\n[Verification: PASS (round {round_num}/{max_rounds}, "
                f"confidence={verdict.confidence})]\n"
                f"<verification_evidence>\n{verdict.raw}\n</verification_evidence>"
            )
            return last_worker_result

        if round_idx < max_rounds - 1:
            findings_text = (
                "\n".join(
                    f"- [{f.get('severity', 'UNKNOWN')}] {f.get('description', 'No description')}"
                    for f in verdict.findings
                )
                if verdict.findings
                else verdict.summary
            )

            current_task = (
                f"{worker_task}\n\n"
                f"=========================================\n"
                f"## [Verification Failed] Your previous attempt was rejected!\n\n"
                f"Fix the following issues and re-execute the task. Do NOT repeat the same mistakes.\n\n"
                f"### Verification Findings\n\n{findings_text}"
            )
            logger.info("[verification] Round %d — FAIL, retrying with feedback", round_num)

    evidence_str = f"\n<verification_evidence>\n{verdict.raw}\n</verification_evidence>" if verdict else ""
    last_worker_result.success = False
    last_worker_result.result = (
        f"{last_worker_result.result}\n\n---\n[Verification: FAIL after {max_rounds} round(s)]{evidence_str}"
    )
    return last_worker_result
