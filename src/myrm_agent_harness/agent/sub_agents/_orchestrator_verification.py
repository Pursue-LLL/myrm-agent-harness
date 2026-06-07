"""Adversarial verification orchestration for subagent outputs.

Worker -> Verifier -> Retry loop with structured verdict parsing.

[INPUT]
- agent.sub_agents.types::SubagentConfig, SubAgentResult, SubAgentStatus, WorkspacePolicy
- toolkits.code_execution (POS: executor proxies for sandboxed verification)

[OUTPUT]
- VerificationVerdict: Parsed verdict from a Verifier agent's structured JSON output.
- run_with_verification: Execute a worker then verify via adversarial verifier.

[POS]
Adversarial verification orchestration — Worker -> Verifier -> Retry loop.
"""

from __future__ import annotations

import dataclasses
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from .manager import SubagentManager

logger = get_agent_logger(__name__)

__all__ = ["VerificationVerdict", "run_with_verification"]


@dataclass(frozen=True, slots=True)
class VerificationVerdict:
    """Parsed verdict from a Verifier agent's structured JSON output."""

    passed: bool
    summary: str
    confidence: str
    findings: list[dict[str, str]]
    raw: str


_VERDICT_JSON_RE = re.compile(r"\{[\s\S]*\"verdict\"\s*:", re.IGNORECASE)


def _parse_verdict(raw_result: str) -> VerificationVerdict:
    """Extract the verification verdict from a Verifier agent's output.

    Handles common LLM output variations: bare JSON, markdown-fenced JSON,
    and partial/malformed responses. Enforces physical execution evidence.
    """
    text = raw_result.strip()

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    else:
        match = _VERDICT_JSON_RE.search(text)
        if match:
            start = match.start()
            depth, end = 0, start
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            text = text[start:end]

    def _enforce_evidence(passed: bool, summary: str, raw: str) -> tuple[bool, str]:
        if not passed:
            return passed, summary
        upper = raw.upper()
        if "STDOUT" not in upper and "STDERR" not in upper and "EXECUTION" not in upper and "TRACEBACK" not in upper:
            return False, (
                "FAIL: Validation rejected. You must provide actual execution log "
                "evidence (STDOUT/STDERR/EXECUTION) to grant a PASS."
            )
        return passed, summary

    try:
        data = json.loads(text)
        verdict_str = str(data.get("verdict", "")).strip().upper()
        passed = verdict_str == "PASS"
        summary = str(data.get("summary", ""))

        passed, summary = _enforce_evidence(passed, summary, raw_result)

        findings_raw = data.get("findings", [])
        findings = [{k: str(v) for k, v in item.items()} for item in findings_raw if isinstance(item, dict)]
        return VerificationVerdict(
            passed=passed,
            summary=summary,
            confidence=str(data.get("confidence", "UNKNOWN")),
            findings=findings,
            raw=raw_result,
        )
    except (json.JSONDecodeError, ValueError):
        pass

    upper = raw_result.upper()
    if '"VERDICT": "PASS"' in upper or '"VERDICT":"PASS"' in upper:
        passed, summary = _enforce_evidence(True, "JSON parse failed; keyword PASS detected", raw_result)
        return VerificationVerdict(
            passed=passed,
            summary=summary,
            confidence="LOW",
            findings=[],
            raw=raw_result,
        )

    return VerificationVerdict(
        passed=False,
        summary="Unable to parse verdict; defaulting to FAIL",
        confidence="LOW",
        findings=[],
        raw=raw_result,
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
) -> SubAgentResult:
    """Execute a worker then verify via an adversarial verifier, retrying on failure.

    Orchestration loop:
      1. Spawn Worker -> get result
      2. Spawn Verifier with worker's output
      3. Parse verdict (PASS/FAIL)
      4. If FAIL and rounds remain -> inject feedback into Worker task, goto 1
      5. Return final Worker result (annotated with verification metadata)
    """
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

    for round_idx in range(max_rounds):
        round_num = round_idx + 1
        worker_task_id = f"verify-worker-{round_num}-{worker_type}"

        logger.info(
            "[verification] Round %d/%d — spawning worker '%s'",
            round_num,
            max_rounds,
            worker_type,
        )
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

        verifier_task_id = f"verify-check-{round_num}-{verifier_type}"

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
        if verifier_task_template:
            if "{worker_result}" in verifier_task_template:
                verifier_task_desc = base_desc + verifier_task_template.replace("{worker_result}", worker_result.result)
            else:
                verifier_task_desc = (
                    base_desc
                    + f"SPECIFIC VERIFICATION CRITERIA:\n{verifier_task_template}\n\n## Worker Output\n\n{worker_result.result}"
                )
        else:
            verifier_task_desc = base_desc + f"## Worker Output\n\n{worker_result.result}"

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

            from langchain_core.tools import tool

            @tool("submit_verdict")
            def submit_verdict(
                passed: bool,
                summary: str,
                findings: list[dict[str, str]],
                confidence: str = "HIGH",
            ) -> str:
                """Submit the final verification verdict. You MUST call this tool to complete your task."""
                context["_verifier_verdict"] = VerificationVerdict(
                    passed=passed,
                    summary=summary,
                    confidence=confidence,
                    findings=findings,
                    raw="[Submitted via Tool Call]",
                )
                return "Verdict submitted successfully. Please complete your response."

            safe_tools.append(submit_verdict)
            return safe_tools

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

        if round_verifier_config.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX:
            current_executor = get_executor()
            if current_executor:
                proxy_executor = ReadonlyExecutorProxy(current_executor)
                with ExecutorContextManager(proxy_executor):
                    verifier_result = await manager.spawn_child(
                        task_id=verifier_task_id,
                        agent_type=verifier_type,
                        task_description=verifier_task_desc,
                        config=round_verifier_config,
                        context=context,
                        tool_registry_getter=verifier_tool_registry_getter,
                        wait=True,
                    )
                context["_verifier_has_executed_code"] = proxy_executor.has_executed_code
            else:
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
            break

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

        if round_verifier_config.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX:
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
