"""Sub-Bot Sandbox Tester and Agent-to-Agent (A2A) Flow Inspector.

[INPUT]
- SubBotTestRequest, custom test runners, A2AFlowStep telemetry events.

[OUTPUT]
- SubBotTestResult, A2AFlowTrace, loop detection diagnostics.

[POS]
- Harness orchestration layer for isolated agent testing and communication flow verification.
"""

from __future__ import annotations

import collections
import time
import uuid
from collections.abc import Callable

from myrm_agent_harness.agent.sub_agents.vertical_presets.presets_catalog import PresetsCatalog
from myrm_agent_harness.agent.sub_agents.vertical_presets.types import (
    A2AFlowStep,
    A2AFlowTrace,
    SubBotTestRequest,
    SubBotTestResult,
)


class SubBotSandboxTester:
    """Isolated unit test runner for specialist sub-bots."""

    def __init__(self, catalog: PresetsCatalog | None = None) -> None:
        self._catalog = catalog or PresetsCatalog()

    def run_test(
        self,
        request: SubBotTestRequest,
        custom_runner: Callable[[SubBotTestRequest], SubBotTestResult] | None = None,
    ) -> SubBotTestResult:
        """Execute a sub-bot test in a sandbox environment and return detailed telemetry."""
        test_id = f"test_{uuid.uuid4().hex[:8]}"
        start_time = time.perf_counter()

        preset = self._catalog.get_preset(request.role_id)
        if preset is None:
            elapsed = (time.perf_counter() - start_time) * 1000
            return SubBotTestResult(
                test_id=test_id,
                role_id=request.role_id,
                success=False,
                output_text="",
                execution_time_ms=round(elapsed, 2),
                logs=[f"Error: Role '{request.role_id}' not found in presets catalog."],
                error_message=f"Unknown role ID: {request.role_id}",
            )

        if custom_runner is not None:
            try:
                res = custom_runner(request)
                res.test_id = test_id
                return res
            except Exception as exc:
                elapsed = (time.perf_counter() - start_time) * 1000
                return SubBotTestResult(
                    test_id=test_id,
                    role_id=request.role_id,
                    success=False,
                    output_text="",
                    execution_time_ms=round(elapsed, 2),
                    logs=[f"Exception during custom runner execution: {exc}"],
                    error_message=str(exc),
                )

        # Baseline sandbox simulation using preset persona configuration
        logs: list[str] = [
            f"Initialized sandbox for preset '{preset.display_name}' ({preset.role_id}).",
            f"Reasoning tier: {preset.reasoning_effort.value}.",
            f"Injected mock inputs: {len(request.mock_inputs)} keys.",
        ]

        tools_used = [f"{preset.recommended_tools[0]}:simulated_call"] if preset.recommended_tools else []
        for t in tools_used:
            logs.append(f"Mock tool execution dispatched: {t}")

        simulated_output = (
            f"[{preset.display_name}]: Processed prompt '{request.test_prompt[:60]}...' "
            f"with mock context {request.mock_inputs}."
        )

        elapsed = (time.perf_counter() - start_time) * 1000
        logs.append(f"Execution finalized in {elapsed:.2f}ms.")

        return SubBotTestResult(
            test_id=test_id,
            role_id=request.role_id,
            success=True,
            output_text=simulated_output,
            tool_calls_made=tools_used,
            execution_time_ms=round(elapsed, 2),
            logs=logs,
        )


class A2AFlowInspector:
    """Inspector and telemetry store for Agent-to-Agent (A2A) message flows with loop detection."""

    def __init__(self) -> None:
        self._traces: dict[str, A2AFlowTrace] = {}

    def record_step(
        self,
        session_id: str,
        root_agent_id: str,
        step: A2AFlowStep,
    ) -> A2AFlowTrace:
        """Append an A2A communication step to the active trace and evaluate loop heuristics."""
        trace = self._traces.get(session_id)
        if trace is None:
            trace = A2AFlowTrace(
                trace_id=f"trace_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                root_agent_id=root_agent_id,
                steps=[],
                total_duration_ms=0.0,
                is_loop_detected=False,
            )
            self._traces[session_id] = trace

        trace.steps.append(step)
        trace.total_duration_ms += step.duration_ms
        trace.is_loop_detected = self._detect_loop(trace.steps)
        return trace

    def get_trace(self, session_id: str) -> A2AFlowTrace | None:
        """Fetch the communication trace for a given session."""
        return self._traces.get(session_id)

    def list_traces(self) -> list[A2AFlowTrace]:
        """List all tracked A2A execution traces."""
        return list(self._traces.values())

    def clear(self) -> None:
        """Reset internal trace store."""
        self._traces.clear()

    @staticmethod
    def _detect_loop(steps: list[A2AFlowStep]) -> bool:
        """Detect potential communication loops or ping-pong deadlocks between agents.

        Checks:
        1. Ping-pong cycle: A -> B followed by B -> A repeatedly (>= 3 times).
        2. Closed directed sub-cycle within the last 6 steps.
        """
        if len(steps) < 4:
            return False

        # Ping-pong check
        recent = steps[-4:]
        pairs = [(s.source_agent_id, s.target_agent_id) for s in recent]
        if (
            pairs[0] == pairs[2]
            and pairs[1] == pairs[3]
            and pairs[0][0] == pairs[1][1]
            and pairs[0][1] == pairs[1][0]
        ):
            return True

        # Graph cycle detection on the sliding window of recent steps
        window = steps[-8:]
        graph: dict[str, list[str]] = collections.defaultdict(list)
        for s in window:
            graph[s.source_agent_id].append(s.target_agent_id)

        # Check for cycles using DFS
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in graph.get(node, []):
                if ((neighbor not in visited and dfs(neighbor)) or neighbor in rec_stack):
                    return True
            rec_stack.remove(node)
            return False

        return any(n not in visited and dfs(n) for n in list(graph.keys()))
