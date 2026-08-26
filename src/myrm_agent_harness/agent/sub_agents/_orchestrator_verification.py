"""Adversarial verification orchestration for subagent outputs.

Worker -> Verifier -> Retry loop with structured verdict parsing.

[INPUT]
- agent.sub_agents.types::SubagentConfig, SubAgentResult, SubAgentStatus, WorkspacePolicy, VerificationSummary
- agent.sub_agents._workspace_diff::take_workspace_snapshot, diff_snapshots (POS: Workspace diff for adversarial verification)
- toolkits.code_execution (POS: executor proxies for sandboxed verification)
- core.events.types::AgentEventType (POS: Streaming event types — VERIFICATION_VERDICT)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: SSE event emission sink)

[OUTPUT]
- VerificationVerdict: Parsed verdict from a Verifier agent's structured JSON output.
- VerificationSummary: Structured adversarial verification outcome attached to SubAgentResult.
- run_with_verification: Execute a worker then verify via adversarial verifier with workspace diff injection and verdict event emission. Preserves dict worker results (isolation merge metadata) while appending verification evidence to `_verification_summary`.

[POS]
Adversarial verification orchestration — Worker -> Verifier -> Retry loop with workspace diff injection and structured verdict events.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import fields
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents._verification_parsing import (
    VerificationVerdict,
    _parse_verdict,
)
from myrm_agent_harness.agent.sub_agents._verifier_round import (
    _execute_verifier_round,
    verify_worker_output,
)
from myrm_agent_harness.agent.sub_agents._workspace_diff import take_workspace_snapshot
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
    VerificationSummary,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

    from .manager import SubagentManager

logger = get_agent_logger(__name__)

__all__ = [
    "VerificationVerdict",
    "_parse_verdict",
    "run_with_verification",
    "verify_worker_output",
]

# Fields mirrored from an internal retry worker onto the visible business node.
# Excludes the three identity/visibility fields managed by the caller
# (business task_id, business agent_type, non-internal visibility flag).
# Derived from the dataclass so future SubAgentResult fields are picked up
# automatically instead of silently drifting out of sync.
_SYNC_MANAGED_FIELDS = frozenset({"task_id", "agent_type", "internal"})
_SYNC_FIELDS = tuple(field.name for field in fields(SubAgentResult) if field.name not in _SYNC_MANAGED_FIELDS)


def _format_worker_output_for_verifier(result: object) -> str:
    """Render worker output for the verifier prompt without dropping structured fields."""
    if isinstance(result, dict):
        text = result.get("text")
        if isinstance(text, str):
            return text
        filtered = {
            key: value
            for key, value in result.items()
            if key
            not in (
                "_workspace_sync_back",
                "_isolated_child_workspace",
                "_isolated_parent_workspace",
                "_verification_summary",
            )
        }
        if filtered:
            return json.dumps(filtered, ensure_ascii=False)
        return str(result)
    return str(result)


def _append_verification_block(result: object, block: str) -> object:
    """Append verification evidence while preserving dict merge metadata."""
    if isinstance(result, dict):
        updated = dict(result)
        prior = updated.get("_verification_summary")
        if isinstance(prior, str) and prior:
            updated["_verification_summary"] = f"{prior}\n\n{block}"
        else:
            updated["_verification_summary"] = block
        text = updated.get("text")
        if isinstance(text, str):
            updated["text"] = f"{text}\n\n{block}"
        return updated
    return f"{result}\n\n{block}"


def _spawn_dict_to_subagent_result(
    payload: dict[str, object],
    *,
    task_id: str,
    agent_type: str,
) -> SubAgentResult:
    raw_result = payload.get("result", "")
    if not isinstance(raw_result, (dict, str)):
        raw_result = str(raw_result)
    status_raw = payload.get("status", SubAgentStatus.COMPLETED)
    status = status_raw if isinstance(status_raw, SubAgentStatus) else SubAgentStatus.COMPLETED
    return SubAgentResult(
        success=bool(payload.get("success", False)),
        task_id=task_id,
        agent_type=agent_type,
        result=raw_result,
        error=str(payload["error"]) if payload.get("error") else "",
        completed_at=time.time(),
        status=status,
    )


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
    cancel_token: CancellationToken | None = None,
    task_id: str | None = None,
    verification_mode: Literal["adversarial", "auditor_blind", "multi_skeptic"] = "adversarial",
) -> SubAgentResult:
    """Execute a worker then verify via an adversarial verifier, retrying on failure.

    When ``task_id`` is provided it becomes the visible business node: the first
    worker runs under that id (``internal=False``) so it shows in the subagent
    tree, while retry workers and verifiers spawn as framework-internal nodes
    (``internal=True``) that are hidden from user-facing surfaces.
    """
    max_rounds = max(1, min(max_rounds, 5))
    current_task = worker_task
    last_worker_result = SubAgentResult(
        success=False,
        task_id=task_id or "verify-init",
        agent_type=worker_type,
        error="Verification not started",
        completed_at=time.time(),
        status=SubAgentStatus.FAILED,
        internal=task_id is None,
    )
    business_result: SubAgentResult | None = None
    verdict = None

    workspace_path = context.get("workspace_path")

    for round_idx in range(max_rounds):
        if cancel_token and cancel_token.is_cancelled:
            last_worker_result.success = False
            last_worker_result.error = "Cancelled"
            _sync_business_result(business_result, last_worker_result, task_id)
            return last_worker_result

        round_num = round_idx + 1
        if round_idx == 0 and task_id:
            worker_task_id = task_id
            worker_internal = False
        else:
            # Internal retry workers get a unique id: parallel delegated tasks
            # share this manager and must not collide on a fixed-format id.
            worker_task_id = f"verify-worker-{round_num}-{worker_type}-{uuid.uuid4().hex[:8]}"
            worker_internal = True

        logger.info(
            "[verification] Round %d/%d — spawning worker '%s'%s [mode=%s]",
            round_num,
            max_rounds,
            worker_type,
            " (internal)" if worker_internal else "",
            verification_mode,
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
            cancel_token=cancel_token,
            internal=worker_internal,
        )
        if isinstance(worker_result, dict):
            worker_result = _spawn_dict_to_subagent_result(
                worker_result,
                task_id=worker_task_id,
                agent_type=worker_type,
            )
        worker_result.internal = worker_result.internal or worker_internal
        if round_idx == 0 and task_id:
            business_result = worker_result
        last_worker_result = worker_result

        if not worker_result.success:
            logger.warning(
                "[verification] Round %d — worker failed: %s",
                round_num,
                worker_result.error,
            )
            break

        if verification_mode == "multi_skeptic":
            skeptic_perspectives = [
                ("Contract & Core Logic", "Verify core logic, inputs, outputs, and requirements strictly."),
                ("Edge Cases & Boundaries", "Test boundary conditions, empty/malformed inputs, timeout, and exceptions."),
                ("Side Effects & Integrity", "Verify that no unintended side-effects, regression, or security gaps exist."),
            ]

            async def _run_single_skeptic(p_title: str, p_rule: str) -> VerificationVerdict | None:
                skeptic_template = (
                    f"### Skeptic Focus: {p_title}\n{p_rule}\n\n{verifier_task_template}"
                    if verifier_task_template
                    else f"### Skeptic Focus: {p_title}\n{p_rule}"
                )
                return await _execute_verifier_round(
                    manager,
                    worker_output=_format_worker_output_for_verifier(worker_result.result),
                    worker_type=worker_type,
                    verifier_type=verifier_type,
                    verifier_config=verifier_config,
                    context=context,
                    tool_registry_getter=tool_registry_getter,
                    round_num=round_num,
                    max_rounds=max_rounds,
                    verifier_task_template=skeptic_template,
                    pre_snapshot=pre_snapshot,
                    cancel_token=cancel_token,
                    auditor_blind=True,
                )

            skeptic_results = await asyncio.gather(
                *[_run_single_skeptic(t, r) for (t, r) in skeptic_perspectives],
                return_exceptions=True,
            )
            valid_verdicts: list[VerificationVerdict] = []
            for res in skeptic_results:
                if isinstance(res, VerificationVerdict):
                    valid_verdicts.append(res)
                elif isinstance(res, Exception):
                    logger.error("[verification] Skeptic execution raised exception: %s", res)

            if not valid_verdicts:
                logger.warning("[verification] All skeptics crashed; fail-closed blocked.")
                last_worker_result.success = False
                last_worker_result.status = SubAgentStatus.BLOCKED
                last_worker_result.error = "Multi-skeptic verifiers crashed unexpectedly (Fail-Closed blocked)."
                _sync_business_result(business_result, last_worker_result, task_id)
                return last_worker_result

            pass_count = sum(1 for v in valid_verdicts if v.passed)
            majority_passed = pass_count >= 2
            confidence = "HIGH" if pass_count == 3 else ("MEDIUM" if pass_count == 2 else "LOW")
            all_findings: list[dict[str, str]] = []
            for v in valid_verdicts:
                all_findings.extend(v.findings)

            combined_summary = (
                f"Multi-Skeptic Voting: {pass_count}/{len(valid_verdicts)} approved "
                f"(majority={'PASS' if majority_passed else 'FAIL'}). "
                + "; ".join(v.summary for v in valid_verdicts if v.summary)
            )
            combined_raw = "\n---\n".join(v.raw for v in valid_verdicts if v.raw)
            verdict = VerificationVerdict(
                passed=majority_passed,
                confidence=confidence,
                summary=combined_summary,
                findings=all_findings,
                raw=combined_raw,
            )
        else:
            is_blind = verification_mode == "auditor_blind"
            try:
                verdict = await _execute_verifier_round(
                    manager,
                    worker_output=_format_worker_output_for_verifier(worker_result.result),
                    worker_type=worker_type,
                    verifier_type=verifier_type,
                    verifier_config=verifier_config,
                    context=context,
                    tool_registry_getter=tool_registry_getter,
                    round_num=round_num,
                    max_rounds=max_rounds,
                    verifier_task_template=verifier_task_template,
                    pre_snapshot=pre_snapshot,
                    cancel_token=cancel_token,
                    auditor_blind=is_blind,
                )
            except Exception as exc:
                logger.error("[verification] Verifier round crashed: %s", exc)
                last_worker_result.success = False
                last_worker_result.status = SubAgentStatus.BLOCKED
                last_worker_result.error = f"Verifier crashed unexpectedly: {exc}"
                _sync_business_result(business_result, last_worker_result, task_id)
                return last_worker_result

        if verdict is None:
            logger.warning("[verification] Verifier returned None verdict; fail-closed blocked.")
            last_worker_result.status = SubAgentStatus.BLOCKED
            last_worker_result.error = "Verifier subagent failed to complete"
            break

        if verdict.passed:
            last_worker_result.verification = VerificationSummary(
                passed=True,
                rounds=round_num,
                max_rounds=max_rounds,
                confidence=verdict.confidence,
                summary=verdict.summary,
                findings=tuple(verdict.findings),
            )
            pass_block = (
                f"---\n[Verification: PASS (round {round_num}/{max_rounds}, "
                f"confidence={verdict.confidence})]\n"
                f"<verification_evidence>\n{verdict.raw}\n</verification_evidence>"
            )
            last_worker_result.result = _append_verification_block(last_worker_result.result, pass_block)
            _sync_business_result(business_result, last_worker_result, task_id)
            return business_result or last_worker_result

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
    if verdict is not None:
        last_worker_result.verification = VerificationSummary(
            passed=False,
            rounds=max_rounds,
            max_rounds=max_rounds,
            confidence=verdict.confidence,
            summary=verdict.summary,
            findings=tuple(verdict.findings),
        )
    fail_block = f"---\n[Verification: FAIL after {max_rounds} round(s)]{evidence_str}"
    last_worker_result.result = _append_verification_block(last_worker_result.result, fail_block)
    _sync_business_result(business_result, last_worker_result, task_id)
    return business_result or last_worker_result


def _sync_business_result(
    business_result: SubAgentResult | None,
    source: SubAgentResult,
    task_id: str | None,
) -> None:
    """Mirror the final worker/verifier outcome onto the visible business node.

    The business node is the first worker's ``SubAgentResult`` registered in
    ``_children_results`` under the business ``task_id``; retry workers are
    internal nodes that must not leak into the tree, so their outcome is copied
    onto the business node in place.
    """
    if business_result is None or business_result is source or not task_id:
        return
    for field_name in _SYNC_FIELDS:
        setattr(business_result, field_name, getattr(source, field_name))
    business_result.task_id = task_id
    business_result.internal = False
