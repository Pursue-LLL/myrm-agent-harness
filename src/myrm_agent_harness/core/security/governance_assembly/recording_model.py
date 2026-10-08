"""Lightweight Recording ChatModel & Offline Governance Test Harness.

Enables zero-model-cost offline verification of full Agent execution pathways
(Interactive Chat, Background Cron, Subagent DAG), asserting governance assembly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from myrm_agent_harness.core.security.governance_assembly.probe import GovernanceAssemblyProbe
from myrm_agent_harness.core.security.governance_assembly.types import (
    IngressSource,
    JsonScalar,
    UngovernedToolExecutionError,
)
from myrm_agent_harness.core.security.governance_assembly.watchdog import (
    RuntimeZeroBypassWatchdog,
    get_governance_signature,
)


@dataclass(frozen=True)
class SyntheticToolCall:
    """Simulated tool call emitted by the recording model."""

    tool_name: str
    tool_args: dict[str, JsonScalar] = field(default_factory=dict)


@dataclass(frozen=True)
class RecordingTurn:
    """Pre-recorded or scripted conversation turn."""

    role: str
    content: str
    tool_calls: tuple[SyntheticToolCall, ...] = ()


class RecordingChatModel:
    """Offline recording/mock chat model for assembly validation."""

    def __init__(self, script: Sequence[RecordingTurn]) -> None:
        self._script = list(script)
        self._step_index = 0
        self._recorded_invocations: list[str] = []

    @property
    def remaining_turns(self) -> int:
        """Remaining turns in the test script."""
        return len(self._script) - self._step_index

    def next_turn(self, input_prompt: str) -> RecordingTurn:
        """Emit next planned turn in the offline test scenario."""
        self._recorded_invocations.append(input_prompt)
        if self._step_index >= len(self._script):
            return RecordingTurn(role="assistant", content="[End of script]")
        turn = self._script[self._step_index]
        self._step_index += 1
        return turn

    def execute_scripted_workflow(
        self,
        ingress_source: IngressSource,
        watchdog: RuntimeZeroBypassWatchdog,
        probe: GovernanceAssemblyProbe,
        tools: Mapping[str, Callable[..., str]],
        prompts: Sequence[str],
    ) -> list[str]:
        """Run simulated workflow, asserting governance wrappers across every invoked tool."""
        results: list[str] = []

        for prompt in prompts:
            turn = self.next_turn(prompt)
            for call in turn.tool_calls:
                target_callable = tools.get(call.tool_name)
                if target_callable is None:
                    raise KeyError(f"Tool '{call.tool_name}' not found in registered tools")

                # Inspect governance signature for probe tracking
                sig = get_governance_signature(target_callable)
                is_governed = sig is not None and sig.is_sealed
                applied_middlewares = sig.applied_middlewares if sig is not None else ()

                # Record in assembly probe
                probe.record_invocation(
                    tool_name=call.tool_name,
                    ingress_source=ingress_source,
                    applied_middlewares=applied_middlewares,
                    is_governed=is_governed,
                    bypassed_guards=() if is_governed else ("ToolInterceptorMiddleware",),
                )

                # Attempt execution through zero-bypass watchdog
                try:
                    output = watchdog.execute_governed_tool(
                        target_callable,
                        call.tool_name,
                        **call.tool_args,
                    )
                    results.append(output)
                except UngovernedToolExecutionError:
                    results.append(f"[BLOCKED_UNGOVERNED::{call.tool_name}]")
                    raise

        return results
