"""Single-round verifier spawn and verify_worker_output entry point.

[INPUT]
- agent.sub_agents._verification_parsing::VerificationVerdict, _parse_verdict, _emit_verification_verdict (POS: Shared verification parsing for sub_agents verifier rounds and delegate verification.)
- agent.sub_agents._workspace_diff::take_workspace_snapshot, diff_snapshots, revert_workspace_mutations (POS: Workspace diff for adversarial verification — stat-based, no git dependency.)
- agent.sub_agents.result_output::answer_text (POS: Subagent result payload (answer text, or a dict carrying isolation merge metadata).)
- agent.sub_agents.types::SubagentConfig, SubAgentResult, SubAgentStatus, WorkspacePolicy (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)
- agent.orchestration.signals.catalog::SUBMIT_VERDICT_SIGNAL (POS: SSOT for control-plane signal names)
- agent.orchestration.signals.verifier::create_submit_verdict_tool (POS: Verifier sub-agents bind ``submit_verdict`` to emit a structured ``VerificationVerdict``.)
- agent.sub_agents.spawn_capability::derive_verifier_capability (POS: The only producer of subagent capability handles.)
- agent.sub_agents.checkpointer::delete_subagent_checkpoint (POS: Releases the checkpoint thread of a verifier abandoned while paused for approval.)
- core.security.ocap::AttenuationError, capability_scope (POS: Foundational zero-trust Object-Capability primitives for Myrm Agent Harness.)
- toolkits.code_execution.executors.execution_evidence::track_execution (POS: Lets a caller that must not trust a model's claim of having run something (the verifier's PASS gate) ask whether the executor really launched a process.)

[OUTPUT]
- verify_worker_output: Verify existing worker output without re-running worker (``None`` = inconclusive round)
- _execute_verifier_round: Internal single-round verifier spawn (``None`` = verifier failed, paused for approval, or PASS without execution evidence)

[POS]
Verifier-only round execution used by Cron post-run delivery assurance and orchestration.
"""

from __future__ import annotations

import contextlib
import dataclasses
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.orchestration.signals.catalog import SUBMIT_VERDICT_SIGNAL
from myrm_agent_harness.agent.sub_agents._verification_parsing import (
    VerificationVerdict,
    _emit_verification_verdict,
    _parse_verdict,
)
from myrm_agent_harness.agent.sub_agents._workspace_diff import (
    diff_snapshots,
    revert_workspace_mutations,
    take_workspace_snapshot,
)
from myrm_agent_harness.agent.sub_agents.checkpointer import delete_subagent_checkpoint
from myrm_agent_harness.agent.sub_agents.result_output import answer_text
from myrm_agent_harness.agent.sub_agents.spawn_capability import derive_verifier_capability
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
    WorkspacePolicy,
)
from myrm_agent_harness.core.security.ocap import AttenuationError, capability_scope
from myrm_agent_harness.toolkits.code_execution.executors.execution_evidence import track_execution
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

    from .manager import SubagentManager

logger = get_agent_logger(__name__)

__all__ = ["verify_worker_output"]


def _build_verifier_tool_registry_getter(
    tool_registry_getter: Callable[[], list[BaseTool]],
    context: dict[str, object],
) -> Callable[[], list[BaseTool]]:
    """Parent tools plus ``submit_verdict``. ``filter_tools`` drops side-effect MCP tools for the
    READ_ONLY_SANDBOX verifier configs all callers pass."""

    def verifier_tool_registry_getter() -> list[BaseTool]:
        from myrm_agent_harness.agent.orchestration.signals.verifier import (
            create_submit_verdict_tool,
        )

        return [*tool_registry_getter(), create_submit_verdict_tool(context)]

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
    cancel_token: CancellationToken | None = None,
    auditor_blind: bool = False,
) -> VerificationVerdict | None:
    """Spawn a verifier subagent for an existing worker output and return the parsed verdict.

    Returns ``None`` when the round is inconclusive: the verifier failed to complete, or it granted
    PASS without ever launching a process (no execution evidence). A ``None`` round emits no verdict
    event and never counts as a FAIL.
    """
    # Unique verifier id: parallel delegated tasks on the same manager must not
    # collide on a fixed-format id (they all run as framework-internal nodes).
    verifier_task_id = f"verify-check-{round_num}-{verifier_type}-{uuid.uuid4().hex[:8]}"
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
        "(via your bash tool) or run curl/ping to physically verify the output. "
        "The workspace is read-only for you, so keep scripts and scratch output under /tmp.\n"
        "2. You MUST include the actual execution logs (STDOUT/STDERR) from your tests in your final response.\n"
        "3. A 'PASS' verdict without execution evidence will be REJECTED by the system, "
        "which records whether you actually ran commands.\n\n"
    )

    if workspace_diff:
        base_desc += (
            f"{workspace_diff}\n\n"
            "IMPORTANT: Review ALL files listed above, not just those mentioned in the Worker Output. "
            "Files modified but not reported by the worker may contain unintended side effects.\n\n"
        )

    if auditor_blind and workspace_diff:
        blind_notice = (
            "## Verification Mode: Auditor Blind\n"
            "Worker subjective narrative is omitted to eliminate confirmation bias. "
            "Inspect and execute test assertions against the physical workspace changes above.\n"
        )
        if verifier_task_template:
            if "{worker_result}" in verifier_task_template:
                verifier_task_desc = base_desc + verifier_task_template.replace("{worker_result}", blind_notice)
            else:
                verifier_task_desc = (
                    base_desc + f"SPECIFIC VERIFICATION CRITERIA:\n{verifier_task_template}\n\n{blind_notice}"
                )
        else:
            verifier_task_desc = base_desc + blind_notice
    elif verifier_task_template:
        if "{worker_result}" in verifier_task_template:
            verifier_task_desc = base_desc + verifier_task_template.replace("{worker_result}", worker_output)
        else:
            verifier_task_desc = (
                base_desc
                + f"SPECIFIC VERIFICATION CRITERIA:\n{verifier_task_template}\n\n## Worker Output\n\n{worker_output}"
            )
    else:
        verifier_task_desc = base_desc + f"## Worker Output\n\n{worker_output}"

    # ``submit_verdict`` is this round's own verdict channel, so a preset allowlist must not strip it.
    # An empty allowlist already means "every parent tool" and has to stay empty.
    round_verifier_config = dataclasses.replace(
        verifier_config,
        tools=(*verifier_config.tools, SUBMIT_VERDICT_SIGNAL) if verifier_config.tools else (),
        display_name=f"Adversarial Verifier ({round_num}/{max_rounds})",
    )

    logger.info(
        "[verification] Round %d/%d — spawning verifier '%s'%s",
        round_num,
        max_rounds,
        verifier_type,
        " [blind]" if auditor_blind else "",
    )

    # The verdict sink is per round: parallel skeptics must not overwrite each other's verdict.
    round_context = dict(context)
    verifier_tool_registry_getter = _build_verifier_tool_registry_getter(tool_registry_getter, round_context)

    verifier_handle = None
    if round_verifier_config.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX:
        try:
            verifier_handle = derive_verifier_capability(verifier_type)
        except AttenuationError as exc:
            logger.warning("[verification] Round %d — verifier capability denied: %s", round_num, exc)
            return None
    handle_scope = capability_scope(verifier_handle) if verifier_handle is not None else contextlib.nullcontext()

    audit_pre_snapshot: dict[str, tuple[float, int]] = {}
    if workspace_path and isinstance(workspace_path, str):
        try:
            audit_pre_snapshot = take_workspace_snapshot(workspace_path)
        except Exception as exc:
            logger.warning(
                "[verification] Audit pre-snapshot failed; this verifier round runs without mutation revert: %s", exc
            )

    try:
        with track_execution() as evidence, handle_scope:
            verifier_result = await manager.spawn_child(
                task_id=verifier_task_id,
                agent_type=verifier_type,
                task_description=verifier_task_desc,
                config=round_verifier_config,
                context=round_context,
                tool_registry_getter=verifier_tool_registry_getter,
                wait=True,
                cancel_token=cancel_token,
                internal=True,
            )
    finally:
        if audit_pre_snapshot and workspace_path and isinstance(workspace_path, str):
            try:
                audit_post_snapshot = take_workspace_snapshot(workspace_path)
                reverted = revert_workspace_mutations(workspace_path, audit_pre_snapshot, audit_post_snapshot)
                if reverted:
                    logger.info(
                        "[verification] Reverted %d mutation(s) created during verification: %s",
                        len(reverted),
                        reverted,
                    )
            except Exception as exc:
                logger.warning("[verification] Mutation restore failed: %s", exc)

    if isinstance(verifier_result, dict):
        verifier_result = SubAgentResult(
            success=bool(verifier_result.get("success", False)),
            task_id=verifier_task_id,
            agent_type=verifier_type,
            result=str(verifier_result.get("result", "")),
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
            internal=True,
        )
    else:
        verifier_result.internal = True

    if verifier_result.status == SubAgentStatus.PENDING_APPROVAL:
        # The verifier is an internal node the user never sees, so nobody can answer its pause. Grading the empty
        # output it has produced so far would turn a verifier that did not finish into a FAIL for the worker.
        logger.warning("[verification] Round %d — verifier is waiting for approval; round inconclusive", round_num)
        await delete_subagent_checkpoint(verifier_task_id)
        return None

    if not verifier_result.success:
        logger.warning(
            "[verification] Round %d — verifier failed: %s",
            round_num,
            verifier_result.error,
        )
        return None

    verdict = round_context.get("_verifier_verdict")
    if isinstance(verdict, VerificationVerdict):
        logger.info(
            "[verification] Round %d — Tool Calling Verdict=%s confidence=%s summary=%s",
            round_num,
            "PASS" if verdict.passed else "FAIL",
            verdict.confidence,
            verdict.summary,
        )
    else:
        verdict = _parse_verdict(answer_text(verifier_result.result))
        logger.info(
            "[verification] Round %d — Regex Verdict=%s confidence=%s summary=%s",
            round_num,
            "PASS" if verdict.passed else "FAIL",
            verdict.confidence,
            verdict.summary,
        )

    if verdict.passed and not evidence.executed:
        # A PASS nobody ran anything for says nothing about the worker's output, so the round is
        # inconclusive (same outcome as a verifier that never finished) rather than a FAIL that would
        # push the worker into pointless rework.
        logger.warning(
            "[verification] Round %d — verifier granted PASS without launching any process; "
            "verdict discarded as inconclusive.",
            round_num,
        )
        return None

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
    auditor_blind: bool = False,
) -> VerificationVerdict | None:
    """Verify an existing worker output without re-running the worker.

    Returns ``None`` when the round is inconclusive (see ``_execute_verifier_round``): callers must
    not read that as a failed verification.
    """
    return await _execute_verifier_round(
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
        auditor_blind=auditor_blind,
    )
