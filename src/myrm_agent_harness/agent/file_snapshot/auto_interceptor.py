"""Auto snapshot interceptor for file-mutating tool calls.

Transparently intercepts file-mutating tool calls (write_file, delete_file,
patch_file, execute_terminal) and takes workspace snapshots before execution.
The LLM never sees this — it's transparent infrastructure.

Implements per-turn dedup to avoid redundant snapshots within a single
conversation turn (same pattern as Hermes checkpoint_manager).

[POS]
Auto-trigger interceptor for file snapshots.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .protocols import FileSnapshotProtocol
from .types import SnapshotTrigger

if TYPE_CHECKING:
    pass

logger = get_agent_logger(__name__)

# Tool names that mutate the filesystem
_MUTATING_TOOLS: dict[str, SnapshotTrigger] = {
    "write_file": SnapshotTrigger.WRITE_FILE,
    "write_file_bytes": SnapshotTrigger.WRITE_FILE,
    "delete_file": SnapshotTrigger.DELETE_FILE,
    "patch_file": SnapshotTrigger.PATCH_FILE,
    "execute_terminal": SnapshotTrigger.EXECUTE_TERMINAL,
    "execute_bash": SnapshotTrigger.EXECUTE_TERMINAL,
}


class AutoSnapshotInterceptor:
    """Intercepts file-mutating tool calls and takes snapshots.

    Per-turn dedup: once a snapshot is taken for a workspace in a given turn,
    subsequent mutations to the same workspace skip the snapshot.

    Usage:
        interceptor = AutoSnapshotInterceptor(snapshot_store)

        # Before tool execution
        await interceptor.before_tool_call(
            tool_name="write_file",
            tool_args={"path": "config.yaml", "content": "..."},
            working_dir="/workspace",
        )

        # After tool execution (optional, for logging)
        await interceptor.after_tool_call(tool_name="write_file", success=True)
    """

    def __init__(self, snapshot_store: FileSnapshotProtocol) -> None:
        self._store = snapshot_store
        # Per-turn dedup: set of (turn_id, workspace_hash) already snapshotted
        self._snapshotted: set[tuple[str, str]] = set()
        self._current_turn_id: str = ""

    def start_turn(self, turn_id: str) -> None:
        """Mark the start of a new conversation turn.

        Clears the per-turn dedup set for the new turn.

        Args:
            turn_id: Unique identifier for this turn (e.g., message_id)
        """
        self._current_turn_id = turn_id
        self._snapshotted.clear()
        logger.debug("AutoSnapshot turn started: %s", turn_id)

    def is_mutating_tool(self, tool_name: str) -> bool:
        """Check if a tool is file-mutating."""
        return tool_name in _MUTATING_TOOLS

    async def before_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, object],
        working_dir: str,
    ) -> str | None:
        """Take a snapshot before a file-mutating tool call.

        Args:
            tool_name: Name of the tool being called
            tool_args: Tool arguments
            working_dir: Current working directory

        Returns:
            Snapshot ID if a snapshot was taken, None otherwise
        """
        if not self.is_mutating_tool(tool_name):
            return None

        trigger = _MUTATING_TOOLS[tool_name]

        # Per-turn dedup
        from .local_store import _workspace_hash

        ws_hash = _workspace_hash(working_dir)
        dedup_key = (self._current_turn_id, ws_hash)
        if dedup_key in self._snapshotted:
            logger.debug(
                "Skipping snapshot for %s (already snapshotted this turn)",
                working_dir,
            )
            return None

        # Take snapshot
        try:
            description = f"Before {tool_name}"
            if tool_name in ("write_file", "write_file_bytes"):
                path = tool_args.get("path", "")
                if path:
                    description = f"Before writing {path}"
            elif tool_name == "delete_file":
                path = tool_args.get("path", "")
                if path:
                    description = f"Before deleting {path}"

            snapshot_id = await self._store.take_snapshot(working_dir, trigger, description)
            self._snapshotted.add(dedup_key)
            logger.info(
                "Auto-snapshot %s before %s (working_dir=%s)",
                snapshot_id,
                tool_name,
                working_dir,
            )
            return snapshot_id

        except Exception as e:
            # Snapshot failure should not block tool execution
            logger.warning("Auto-snapshot failed before %s: %s", tool_name, e)
            return None

    async def after_tool_call(
        self,
        tool_name: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Called after tool execution (for logging/monitoring).

        Args:
            tool_name: Name of the tool that was called
            success: Whether the tool executed successfully
            error: Error message if failed
        """
        if not self.is_mutating_tool(tool_name):
            return

        if not success:
            logger.warning(
                "File-mutating tool %s failed: %s",
                tool_name,
                error or "unknown error",
            )
