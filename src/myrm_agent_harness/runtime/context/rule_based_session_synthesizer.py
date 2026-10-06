"""Rule-based session synthesizer for cross-session handoff generation.

Extracts deterministic facts (touched files, executed commands, decisions,
todos, pitfalls) directly from session conversation turns without LLM hallucination.
"""

import re
import time
from collections.abc import Mapping

from myrm_agent_harness.runtime.context.cross_session_handoff_types import (
    CrossSessionHandoffContract,
    HandoffDecisionItem,
    HandoffPitfallItem,
    HandoffStatus,
    HandoffTodoItem,
)


class RuleBasedSessionSynthesizer:
    """Extracts deterministic facts and constructs structured handoff contracts."""

    def __init__(self, agent_profile: str = "general_agent") -> None:
        self._agent_profile = agent_profile

    def synthesize_from_records(
        self,
        session_id: str,
        turn_records: list[Mapping[str, object]],
        task_summary: str = "",
    ) -> CrossSessionHandoffContract:
        """Parse session history turns and generate an immutable handoff contract."""
        touched_files: set[str] = set()
        executed_commands: list[str] = []
        decisions: list[HandoffDecisionItem] = []
        todos: list[HandoffTodoItem] = []
        pitfalls: list[HandoffPitfallItem] = []

        now = time.time()
        dec_counter = 1
        todo_counter = 1
        pitfall_counter = 1

        for turn in turn_records:
            role = str(turn.get("role", ""))
            content = str(turn.get("content", ""))
            tool_calls = turn.get("tool_calls")
            tool_name = str(turn.get("tool_name", ""))
            tool_output = str(turn.get("tool_output", ""))

            # 1. Extract touched files and executed commands from tool calls
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        self._extract_tool_artifacts(
                            tc, touched_files, executed_commands
                        )

            # Direct tool record format
            if tool_name:
                self._extract_single_tool(
                    tool_name, turn, touched_files, executed_commands
                )

            # 2. Extract decisions from assistant messages
            if role == "assistant" and content:
                for match in re.finditer(
                    r"(?:\[Decision\]|Decision:|<decision>)(.*?)(?:</decision>|\n\n|$)",
                    content,
                    re.IGNORECASE | re.DOTALL,
                ):
                    raw_dec = match.group(1).strip()
                    if raw_dec:
                        decisions.append(
                            HandoffDecisionItem(
                                decision_id=f"DEC-{dec_counter:03d}",
                                topic=raw_dec[:60],
                                rationale=raw_dec,
                                timestamp=now,
                            )
                        )
                        dec_counter += 1

            # 3. Extract TODOs from messages
            if content:
                for line in content.splitlines():
                    line_s = line.strip()
                    if line_s.startswith("- [ ]") or line_s.upper().startswith("TODO:"):
                        todo_text = line_s.replace("- [ ]", "").replace("TODO:", "").strip()
                        if todo_text:
                            todos.append(
                                HandoffTodoItem(
                                    task_id=f"TODO-{todo_counter:03d}",
                                    description=todo_text,
                                    priority="P1",
                                    is_completed=False,
                                )
                            )
                            todo_counter += 1

            # 4. Extract pitfalls from error outputs
            if tool_output and ("error" in tool_output.lower() or "failed" in tool_output.lower()):
                summary_line = tool_output.strip().splitlines()[0][:100]
                pitfalls.append(
                    HandoffPitfallItem(
                        warning_id=f"PIT-{pitfall_counter:03d}",
                        context=f"Tool `{tool_name}` failure",
                        recommendation=summary_line,
                    )
                )
                pitfall_counter += 1

        handoff_id = f"HDF-{session_id[-8:]}-{int(now)}"
        summary = task_summary or f"Session {session_id} state handoff"

        return CrossSessionHandoffContract(
            handoff_id=handoff_id,
            source_session_id=session_id,
            created_at=now,
            source_agent_profile=self._agent_profile,
            target_task_summary=summary,
            decisions=decisions,
            todos=todos,
            pitfalls=pitfalls,
            touched_files=sorted(touched_files),
            executed_commands_summary=executed_commands[:20],
            status=HandoffStatus.PENDING,
        )

    def _extract_tool_artifacts(
        self,
        tc: Mapping[str, object],
        touched_files: set[str],
        executed_commands: list[str],
    ) -> None:
        fn_name = str(tc.get("name", ""))
        args = tc.get("arguments") or tc.get("args")
        if isinstance(args, dict):
            self._handle_args(fn_name, args, touched_files, executed_commands)

    def _extract_single_tool(
        self,
        tool_name: str,
        turn: Mapping[str, object],
        touched_files: set[str],
        executed_commands: list[str],
    ) -> None:
        args = turn.get("arguments") or turn.get("args")
        if isinstance(args, dict):
            self._handle_args(tool_name, args, touched_files, executed_commands)

    def _handle_args(
        self,
        tool_name: str,
        args: Mapping[str, object],
        touched_files: set[str],
        executed_commands: list[str],
    ) -> None:
        # File edits
        for key in ("TargetFile", "target_file", "path", "file_path", "filename"):
            if key in args:
                touched_files.add(str(args[key]))

        # Shell commands
        for key in ("CommandLine", "command", "cmd"):
            if key in args:
                cmd_str = str(args[key]).strip()
                if cmd_str and cmd_str not in executed_commands:
                    executed_commands.append(cmd_str)
