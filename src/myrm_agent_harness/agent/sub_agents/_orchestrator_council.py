"""Council orchestration — multi-expert cross-review with chair synthesis.

Three-phase orchestration primitive:
  Phase 1 (Independent): N experts analyse in parallel, each with tools.
  Phase 2 (Cross-Review): Each expert sees others' opinions and rebuts.
  Phase 3 (Chair Synthesis): A chair agent synthesises all opinions into a
      structured CouncilResult with consensus/divergence/action-items.

[INPUT]
- agent.sub_agents.types::SubagentConfig, SubAgentResult, SubAgentStatus, CouncilOpinion, CouncilResult
- agent.sub_agents.prompts::DEFAULT_COUNCIL_CROSS_REVIEW_PROMPT, DEFAULT_COUNCIL_CHAIR_PROMPT
- core.events.types::AgentEventType (POS: Streaming event types — COUNCIL_PHASE)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: SSE event emission sink)

[OUTPUT]
- run_council: Multi-expert council orchestration with cross-review rounds.

[POS]
Council orchestration — multi-expert parallel analysis with cross-review debate and chair synthesis.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents.prompts import (
    DEFAULT_COUNCIL_CHAIR_PROMPT,
    DEFAULT_COUNCIL_CROSS_REVIEW_PROMPT,
)
from myrm_agent_harness.agent.sub_agents.types import (
    CouncilOpinion,
    CouncilResult,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

    from .manager import SubagentManager

logger = get_agent_logger(__name__)

__all__ = ["run_council"]


def _get_wait_children() -> Callable[..., Awaitable[dict[str, object]]]:
    """Lazy import to avoid circular dependency with orchestrator.py."""
    from .orchestrator import wait_children
    return wait_children


async def _emit_council_phase(
    phase: str,
    round_num: int,
    max_rounds: int,
    expert_count: int,
    detail: str = "",
) -> None:
    """Emit a COUNCIL_PHASE SSE event for frontend visualisation."""
    from myrm_agent_harness.core.events.types import AgentEventType
    from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

    sink = get_tool_progress_sink()
    if not sink:
        return
    try:
        await sink.emit({
            "type": AgentEventType.COUNCIL_PHASE.value,
            "data": {
                "phase": phase,
                "round": round_num,
                "max_rounds": max_rounds,
                "expert_count": expert_count,
                "detail": detail[:300],
            },
        })
    except Exception as exc:
        logger.debug("[council] Failed to emit COUNCIL_PHASE event: %s", exc)


def _format_opinions_for_injection(
    opinions: list[CouncilOpinion],
    exclude_expert: str,
) -> str:
    """Format other experts' opinions for context injection in cross-review."""
    parts: list[str] = []
    for op in opinions:
        if op.expert_id == exclude_expert:
            continue
        parts.append(
            f"### Expert: {op.expert_id} (role: {op.agent_type})\n\n"
            f"{op.content}\n"
        )
    return "\n---\n".join(parts) if parts else "(No other opinions available)"


def _format_all_opinions(opinions: list[CouncilOpinion]) -> str:
    """Format all opinions across all rounds for the chair."""
    by_round: dict[int, list[CouncilOpinion]] = {}
    for op in opinions:
        by_round.setdefault(op.round_num, []).append(op)

    parts: list[str] = []
    for rnd in sorted(by_round):
        label = "Independent Analysis" if rnd == 1 else f"Cross-Review Round {rnd - 1}"
        parts.append(f"## Round {rnd}: {label}\n")
        for op in by_round[rnd]:
            parts.append(
                f"### Expert: {op.expert_id} (role: {op.agent_type})\n\n"
                f"{op.content}\n"
            )
    return "\n---\n".join(parts)


def _parse_chair_sections(text: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Extract consensus, divergences, and action items from the chair's output."""
    def _extract_list(header_pattern: str, content: str) -> list[str]:
        match = re.search(header_pattern, content, re.IGNORECASE)
        if not match:
            return []
        start = match.end()
        next_header = re.search(r"\n#{1,3}\s", content[start:])
        section = content[start: start + next_header.start()] if next_header else content[start:]
        items: list[str] = []
        for line in section.strip().splitlines():
            stripped = line.strip()
            if stripped and stripped[0] in "-*•" and len(stripped) > 2:
                items.append(stripped[1:].strip())
            elif stripped:
                num_match = re.match(r"^(\d+)[.)\s]", stripped)
                if num_match:
                    items.append(stripped[num_match.end():].strip())
        return items

    consensus = _extract_list(r"#{1,3}\s*\d*\.?\s*Consensus\s*Points?", text)
    divergences = _extract_list(r"#{1,3}\s*\d*\.?\s*Divergences?", text)
    actions = _extract_list(r"#{1,3}\s*\d*\.?\s*Action\s*Items?", text)
    return tuple(consensus), tuple(divergences), tuple(actions)


async def run_council(
    manager: SubagentManager,
    task_description: str,
    expert_configs: list[tuple[str, SubagentConfig]],
    context: dict[str, object],
    tool_registry_getter: Callable[[], list[BaseTool]],
    *,
    chair_config: SubagentConfig | None = None,
    cross_review_rounds: int = 1,
    cross_review_prompt_template: str = "",
    chair_prompt_template: str = "",
    cancel_token: CancellationToken | None = None,
) -> CouncilResult:
    """Run a multi-expert council session with cross-review and chair synthesis.

    Args:
        manager: SubagentManager instance for spawning experts.
        task_description: The topic/question for the council to analyse.
        expert_configs: List of (agent_type, config) per expert.
        context: Shared execution context.
        tool_registry_getter: Tool provider for expert agents.
        chair_config: Config for the synthesis chair agent.
            Falls back to the first expert's config with a chair prompt.
        cross_review_rounds: Number of cross-review iterations (default 1).
        cross_review_prompt_template: Custom cross-review prompt
            (must contain ``{other_opinions}``).
        chair_prompt_template: Custom chair prompt
            (must contain ``{all_opinions}``).
        cancel_token: Propagated to each spawned child.

    Returns:
        CouncilResult with synthesis, consensus, divergences, and action items.
    """
    if len(expert_configs) < 2:
        return CouncilResult(
            success=False,
            synthesis="",
            error="Council requires at least 2 experts",
        )

    t0 = time.monotonic()
    batch_id = uuid.uuid4().hex[:8]
    all_opinions: list[CouncilOpinion] = []
    cross_review_rounds = max(1, min(cross_review_rounds, 3))

    cr_template = cross_review_prompt_template or DEFAULT_COUNCIL_CROSS_REVIEW_PROMPT
    ch_template = chair_prompt_template or DEFAULT_COUNCIL_CHAIR_PROMPT

    expert_ids = [f"expert-{i}-{atype}" for i, (atype, _) in enumerate(expert_configs)]
    wait_children = _get_wait_children()

    # ---------------------------------------------------------------
    # Phase 1: Independent Analysis (parallel)
    # ---------------------------------------------------------------
    await _emit_council_phase("independent", 1, cross_review_rounds + 2, len(expert_configs))
    logger.info("[council:%s] Phase 1 — %d experts independent analysis", batch_id, len(expert_configs))

    phase1_task_ids: list[str] = []
    for idx, (agent_type, config) in enumerate(expert_configs):
        task_id = f"council-{batch_id}-p1-{idx}-{agent_type}"
        phase1_task_ids.append(task_id)
        await manager.spawn_child(
            task_id=task_id,
            agent_type=agent_type,
            task_description=task_description,
            config=config,
            context=context,
            tool_registry_getter=tool_registry_getter,
            wait=False,
            cancel_token=cancel_token,
        )

    await wait_children(manager, phase1_task_ids, min_success_rate=0.0)

    for idx, task_id in enumerate(phase1_task_ids):
        agent_type = expert_configs[idx][0]
        completed = manager.child_results.get(task_id)
        success = completed is not None and completed.success
        content = completed.result if completed and completed.success else (completed.error if completed else "")
        duration = completed.duration_seconds if completed else 0.0
        all_opinions.append(CouncilOpinion(
            expert_id=expert_ids[idx],
            agent_type=agent_type,
            round_num=1,
            content=content,
            success=success,
            duration_seconds=duration,
        ))

    successful_phase1 = sum(1 for o in all_opinions if o.success)
    if successful_phase1 < 1:
        return CouncilResult(
            success=False,
            synthesis="",
            opinions=tuple(all_opinions),
            rounds_completed=1,
            total_duration_seconds=time.monotonic() - t0,
            error="All experts failed in Phase 1",
        )

    if cancel_token and cancel_token.is_cancelled:
        return CouncilResult(
            success=False,
            synthesis="",
            opinions=tuple(all_opinions),
            rounds_completed=1,
            total_duration_seconds=time.monotonic() - t0,
            error="Cancelled",
        )

    # ---------------------------------------------------------------
    # Phase 2: Cross-Review (parallel per round)
    # ---------------------------------------------------------------
    for cr_round in range(cross_review_rounds):
        round_num = cr_round + 2
        await _emit_council_phase("cross_review", round_num, cross_review_rounds + 2, len(expert_configs))
        logger.info("[council:%s] Phase 2 — cross-review round %d/%d", batch_id, cr_round + 1, cross_review_rounds)

        previous_round_opinions = [o for o in all_opinions if o.round_num == round_num - 1 and o.success]

        cr_task_ids: list[str] = []
        for idx, (agent_type, config) in enumerate(expert_configs):
            other_opinions_text = _format_opinions_for_injection(previous_round_opinions, expert_ids[idx])
            cr_prompt = cr_template.replace("{other_opinions}", other_opinions_text)

            own_previous = next(
                (o for o in previous_round_opinions if o.expert_id == expert_ids[idx]), None
            )
            full_task = (
                f"## Original Task\n\n{task_description}\n\n"
                f"## Your Previous Analysis\n\n{own_previous.content if own_previous else '(none)'}\n\n"
                f"## Cross-Review Instructions\n\n{cr_prompt}"
            )

            cr_config = dc_replace(config, description=f"交叉审查 [{cr_round + 1}/{cross_review_rounds}]")
            task_id = f"council-{batch_id}-cr{cr_round + 1}-{idx}-{agent_type}"
            cr_task_ids.append(task_id)

            await manager.spawn_child(
                task_id=task_id,
                agent_type=agent_type,
                task_description=full_task,
                config=cr_config,
                context=context,
                tool_registry_getter=tool_registry_getter,
                wait=False,
                cancel_token=cancel_token,
            )

        await wait_children(manager, cr_task_ids, min_success_rate=0.0)

        for idx, task_id in enumerate(cr_task_ids):
            agent_type = expert_configs[idx][0]
            completed = manager.child_results.get(task_id)
            success = completed is not None and completed.success
            content = completed.result if completed and completed.success else ""
            duration = completed.duration_seconds if completed else 0.0
            all_opinions.append(CouncilOpinion(
                expert_id=expert_ids[idx],
                agent_type=agent_type,
                round_num=round_num,
                content=content,
                success=success,
                duration_seconds=duration,
            ))

        if cancel_token and cancel_token.is_cancelled:
            return CouncilResult(
                success=False,
                synthesis="",
                opinions=tuple(all_opinions),
                rounds_completed=round_num,
                total_duration_seconds=time.monotonic() - t0,
                error="Cancelled",
            )

    # ---------------------------------------------------------------
    # Phase 3: Chair Synthesis
    # ---------------------------------------------------------------
    final_round = cross_review_rounds + 2
    await _emit_council_phase("synthesis", final_round, final_round, len(expert_configs))
    logger.info("[council:%s] Phase 3 — chair synthesis", batch_id)

    all_opinions_text = _format_all_opinions([o for o in all_opinions if o.success])
    chair_task_desc = ch_template.replace("{all_opinions}", all_opinions_text)

    resolved_chair = chair_config or dc_replace(
        expert_configs[0][1],
        system_prompt="You are a council chair responsible for synthesising expert opinions.",
        description="委员会主席综合",
        display_name="Council Chair",
    )

    chair_task_id = f"council-{batch_id}-chair"
    chair_result = await manager.spawn_child(
        task_id=chair_task_id,
        agent_type="council-chair",
        task_description=f"## Council Topic\n\n{task_description}\n\n{chair_task_desc}",
        config=resolved_chair,
        context=context,
        tool_registry_getter=tool_registry_getter,
        wait=True,
        cancel_token=cancel_token,
    )

    if isinstance(chair_result, dict):
        chair_result = SubAgentResult(
            success=bool(chair_result.get("success", False)),
            task_id=chair_task_id,
            agent_type="council-chair",
            result=str(chair_result.get("result", "")),
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
        )

    elapsed = time.monotonic() - t0

    if not chair_result.success:
        return CouncilResult(
            success=False,
            synthesis="",
            opinions=tuple(all_opinions),
            rounds_completed=final_round,
            total_duration_seconds=elapsed,
            error=f"Chair synthesis failed: {chair_result.error}",
        )

    consensus, divergences, action_items = _parse_chair_sections(chair_result.result)

    logger.info(
        "[council:%s] Complete — %d experts, %d rounds, %.1fs, %d consensus, %d divergences",
        batch_id,
        len(expert_configs),
        final_round,
        elapsed,
        len(consensus),
        len(divergences),
    )

    return CouncilResult(
        success=True,
        synthesis=chair_result.result,
        consensus_points=consensus,
        divergences=divergences,
        action_items=action_items,
        opinions=tuple(all_opinions),
        rounds_completed=final_round,
        total_duration_seconds=elapsed,
    )
