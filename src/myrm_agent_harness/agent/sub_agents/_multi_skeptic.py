"""Parallel multi-skeptic voting for adversarial verification.

[INPUT]
- agent.sub_agents._verification_parsing::VerificationVerdict (POS: Shared verification parsing for sub_agents verifier rounds and delegate verification.)
- agent.sub_agents._verifier_round::_execute_verifier_round (POS: Verifier-only round execution used by Cron post-run delivery assurance and orchestration.)
- agent.sub_agents.types::SubagentConfig (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)

[OUTPUT]
- vote_with_skeptics: Run three blind skeptic rounds in parallel and merge their conclusive verdicts by majority

[POS]
Multi-skeptic majority voting behind ``run_with_verification(verification_mode="multi_skeptic")``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents._verification_parsing import VerificationVerdict
from myrm_agent_harness.agent.sub_agents._verifier_round import _execute_verifier_round
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

    from .manager import SubagentManager

logger = get_agent_logger(__name__)

__all__ = ["vote_with_skeptics"]

_SKEPTIC_PERSPECTIVES: tuple[tuple[str, str], ...] = (
    ("Contract & Core Logic", "Verify core logic, inputs, outputs, and requirements strictly."),
    ("Edge Cases & Boundaries", "Test boundary conditions, empty/malformed inputs, timeout, and exceptions."),
    ("Side Effects & Integrity", "Verify that no unintended side-effects, regression, or security gaps exist."),
)

_PASS_QUORUM = 2
"""Conclusive PASS votes required for the majority to pass."""


def _skeptic_task_template(title: str, rule: str, verifier_task_template: str) -> str:
    focus = f"### Skeptic Focus: {title}\n{rule}"
    return f"{focus}\n\n{verifier_task_template}" if verifier_task_template else focus


async def vote_with_skeptics(
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
    verifier_task_template: str,
    pre_snapshot: dict[str, tuple[float, int]] | None,
    cancel_token: CancellationToken | None,
) -> VerificationVerdict | None:
    """Merge the skeptics' conclusive verdicts into one majority verdict.

    A skeptic that crashed or granted PASS without execution evidence casts no vote. Returns ``None``
    when the votes cannot decide: no skeptic was conclusive, or the only conclusive vote is a lone PASS
    that cannot reach the quorum and so proves no defect either.
    """
    results = await asyncio.gather(
        *(
            _execute_verifier_round(
                manager,
                worker_output=worker_output,
                worker_type=worker_type,
                verifier_type=verifier_type,
                verifier_config=verifier_config,
                context=context,
                tool_registry_getter=tool_registry_getter,
                round_num=round_num,
                max_rounds=max_rounds,
                verifier_task_template=_skeptic_task_template(title, rule, verifier_task_template),
                pre_snapshot=pre_snapshot,
                cancel_token=cancel_token,
                auditor_blind=True,
            )
            for title, rule in _SKEPTIC_PERSPECTIVES
        ),
        return_exceptions=True,
    )

    verdicts: list[VerificationVerdict] = []
    for result in results:
        if isinstance(result, VerificationVerdict):
            verdicts.append(result)
        elif isinstance(result, Exception):
            logger.error("[verification] Skeptic execution raised exception: %s", result)

    pass_count = sum(1 for v in verdicts if v.passed)
    no_defect_found = pass_count == len(verdicts)
    if no_defect_found and pass_count < _PASS_QUORUM:
        return None

    majority_passed = pass_count >= _PASS_QUORUM
    if pass_count == len(_SKEPTIC_PERSPECTIVES):
        confidence = "HIGH"
    elif pass_count == _PASS_QUORUM:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    summary = (
        f"Multi-Skeptic Voting: {pass_count}/{len(verdicts)} approved "
        f"(majority={'PASS' if majority_passed else 'FAIL'}). " + "; ".join(v.summary for v in verdicts if v.summary)
    )
    return VerificationVerdict(
        passed=majority_passed,
        confidence=confidence,
        summary=summary,
        findings=[finding for v in verdicts for finding in v.findings],
        raw="\n---\n".join(v.raw for v in verdicts if v.raw),
    )
