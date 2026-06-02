"""Catchup session brief extractor.

[INPUT]
None (pure utility)

[OUTPUT]
- CatchupBrief: Pydantic model for catchup summary
- CatchupBriefExtractor: Pure function class to extract brief from messages

[POS]
Extracts structured summary (files touched, tools used, etc.) from agent messages for the Catchup feature.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CatchupBrief(BaseModel):
    """Structured summary of an agent session for Catchup Inbox."""

    last_user_prompt: str = Field(default="", description="The last message sent by the user")
    latest_agent_response: str = Field(default="", description="The latest text response from the agent")
    files_touched: list[str] = Field(default_factory=list, description="List of unique file paths modified")
    tool_counts: dict[str, int] = Field(default_factory=dict, description="Counts of each tool used")
    activity_steps: list[str] = Field(default_factory=list, description="High-level activity descriptions")
    needs_from_user: str | None = Field(default=None, description="What the agent needs from the user (if any)")
    status: str = Field(default="completed", description="Status of the session (e.g., completed, waiting, error)")


class CatchupBriefExtractor:
    """Pure functional extractor for CatchupBrief."""

    @staticmethod
    def extract(
        messages: list[dict[str, Any]],
        progress_steps: list[dict[str, Any]],
        status: str = "completed"
    ) -> CatchupBrief:
        """Extract a CatchupBrief from raw message data and progress steps.

        Args:
            messages: List of message dicts containing 'role' and 'content'
            progress_steps: List of progress step dicts from extra_data['progressSteps']
            status: The overall status of the session

        Returns:
            CatchupBrief containing the extracted summary
        """
        brief = CatchupBrief(status=status)

        # Extract last user prompt and latest agent response
        for msg in reversed(messages):
            role = msg.get("role")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                if role == "user" and not brief.last_user_prompt:
                    brief.last_user_prompt = content
                elif role == "assistant" and not brief.latest_agent_response:
                    brief.latest_agent_response = content

            if brief.last_user_prompt and brief.latest_agent_response:
                break

        # Extract tool counts and files touched from progress steps
        files_touched_set: set[str] = set()

        for step in progress_steps:
            tool_name = step.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name:
                continue

            # Update tool counts
            brief.tool_counts[tool_name] = brief.tool_counts.get(tool_name, 0) + 1

            # Extract file paths from specific tools
            items = step.get("items")
            if isinstance(items, list) and items:
                for item in items:
                    if not isinstance(item, dict):
                        continue

                    # Handle file_write_tool, file_edit_tool, etc.
                    if tool_name in ("file_write_tool", "file_edit_tool", "file_replace_tool", "file_patch_tool"):
                        path = item.get("path")
                        if isinstance(path, str) and path:
                            files_touched_set.add(path)

                    # Add activity steps for important actions
                    if tool_name == "bash_tool" or tool_name == "shell_tool":
                        cmd = item.get("command")
                        if isinstance(cmd, str) and cmd:
                            # Only add short commands or truncated long commands
                            short_cmd = cmd.split("\\n")[0][:50]
                            if len(cmd) > 50:
                                short_cmd += "..."
                            brief.activity_steps.append(f"Ran command: {short_cmd}")
                    elif tool_name == "web_search_tool":
                        query = item.get("query")
                        if isinstance(query, str) and query:
                            brief.activity_steps.append(f"Searched web for: {query}")

        brief.files_touched = sorted(list(files_touched_set))

        # Infer needs from user
        if status == "waiting_for_approval":
            brief.needs_from_user = "Agent is waiting for your approval to proceed."
        elif status == "error":
            brief.needs_from_user = "Agent encountered an error and stopped."
        elif brief.latest_agent_response.strip().endswith("?"):
            brief.needs_from_user = "Agent asked a question."

        # Deduplicate activity steps (keep last 5)
        unique_steps = []
        seen_steps = set()
        for step in reversed(brief.activity_steps):
            if step not in seen_steps:
                unique_steps.append(step)
                seen_steps.add(step)
            if len(unique_steps) >= 5:
                break
        brief.activity_steps = list(reversed(unique_steps))

        return brief
