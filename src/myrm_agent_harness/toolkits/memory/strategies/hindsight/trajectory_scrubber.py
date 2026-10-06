# [POS] toolkits/memory/strategies/hindsight/trajectory_scrubber.py
# [INPUT] FailureTurn, FailureTrajectory
# [OUTPUT] FailureTrajectoryScrubber

"""Scrubber for failed task trajectories, extracting critical turns and error turning points."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.strategies.hindsight.types import (
    FailureTrajectory,
    FailureTurn,
)

_ERROR_KEYWORDS: tuple[str, ...] = (
    "error",
    "exception",
    "failed",
    "permission denied",
    "command not found",
    "exit code 1",
    "timeout",
    "unauthorized",
    "invalid argument",
    "cannot access",
)


class FailureTrajectoryScrubber:
    """Cleans raw execution history and isolates the pivotal error turning point."""

    def __init__(self, max_output_chars: int = 1000) -> None:
        self.max_output_chars = max_output_chars

    def sanitize_output(self, raw_output: str) -> str:
        """Truncate excessive output while preserving head and tail diagnostic context."""
        text = raw_output.strip()
        if len(text) <= self.max_output_chars:
            return text
        head_len = self.max_output_chars // 2
        tail_len = self.max_output_chars // 2
        return f"{text[:head_len]}\n... [truncated] ...\n{text[-tail_len:]}"

    def scrub(
        self,
        task_id: str,
        task_goal: str,
        turns: list[FailureTurn],
        terminal_error: str,
        max_turns: int = 5,
    ) -> FailureTrajectory:
        """Extract recent tail turns and clean tool outputs."""
        sliced_turns = turns[-max_turns:] if len(turns) > max_turns else turns

        cleaned_turns: list[FailureTurn] = []
        for t in sliced_turns:
            cleaned_turns.append(
                FailureTurn(
                    turn_index=t.turn_index,
                    tool_name=t.tool_name,
                    tool_input=dict(t.tool_input),
                    tool_output=self.sanitize_output(t.tool_output),
                    error_message=t.error_message.strip(),
                    timestamp=t.timestamp,
                )
            )

        return FailureTrajectory(
            task_id=task_id,
            task_goal=task_goal.strip(),
            turns=cleaned_turns,
            terminal_error=terminal_error.strip(),
        )

    def locate_turning_point(
        self, trajectory: FailureTrajectory
    ) -> FailureTurn | None:
        """Find the earliest turn that introduced an unhandled error or failure indicator."""
        for turn in trajectory.turns:
            if turn.error_message:
                return turn
            output_lower = turn.tool_output.lower()
            if any(kw in output_lower for kw in _ERROR_KEYWORDS):
                return turn

        # Fallback to last turn if trajectory exists
        return trajectory.turns[-1] if trajectory.turns else None
