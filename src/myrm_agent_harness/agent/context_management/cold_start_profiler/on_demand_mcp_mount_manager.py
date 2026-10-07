"""On-demand MCP Mount Manager providing dynamic session-level hibernation and JIT activation.

Allows users and heuristic intent detectors to put heavyweight external MCP servers
to sleep, removing their bulky schemas from the active context window until requested.
"""

from __future__ import annotations

import re
from typing import Sequence

from .cold_start_profiler_types import (
    McpMountMutationResult,
    McpServerDescriptor,
    McpServerMountState,
)


class OnDemandMcpMountManager:
    """Manages MCP server mounting states and performs Just-In-Time re-activation upon prompt intent."""

    def __init__(self, initial_servers: Sequence[McpServerDescriptor] | None = None) -> None:
        self._servers: dict[str, McpServerDescriptor] = {
            s.server_id: s for s in (initial_servers or [])
        }

    def register_server(self, descriptor: McpServerDescriptor) -> None:
        """Register or update an MCP server descriptor."""
        self._servers[descriptor.server_id] = descriptor

    def hibernate_server(self, server_id: str) -> McpMountMutationResult:
        """Put an active MCP server to sleep, evicting its tool schemas from active context."""
        server = self._servers.get(server_id)
        if not server:
            return McpMountMutationResult(
                server_id=server_id,
                old_state=McpServerMountState.SLEEPING,
                new_state=McpServerMountState.SLEEPING,
                tokens_delta=0,
                message=f"MCP server '{server_id}' not found.",
            )

        old_state = server.mount_state
        if old_state == McpServerMountState.SLEEPING:
            return McpMountMutationResult(
                server_id=server_id,
                old_state=old_state,
                new_state=old_state,
                tokens_delta=0,
                message=f"Server '{server_id}' is already sleeping.",
            )

        updated = McpServerDescriptor(
            server_id=server.server_id,
            display_name=server.display_name,
            tool_names=server.tool_names,
            estimated_schema_tokens=server.estimated_schema_tokens,
            mount_state=McpServerMountState.SLEEPING,
            tags=server.tags,
        )
        self._servers[server_id] = updated

        return McpMountMutationResult(
            server_id=server_id,
            old_state=old_state,
            new_state=McpServerMountState.SLEEPING,
            tokens_delta=-server.estimated_schema_tokens,
            message=f"Hibernated '{server.display_name}'; freed ~{server.estimated_schema_tokens} tokens.",
        )

    def wake_server(self, server_id: str) -> McpMountMutationResult:
        """Re-activate a sleeping or standby MCP server into the active tool binding."""
        server = self._servers.get(server_id)
        if not server:
            return McpMountMutationResult(
                server_id=server_id,
                old_state=McpServerMountState.SLEEPING,
                new_state=McpServerMountState.SLEEPING,
                tokens_delta=0,
                message=f"MCP server '{server_id}' not found.",
            )

        old_state = server.mount_state
        if old_state == McpServerMountState.MOUNTED_ACTIVE:
            return McpMountMutationResult(
                server_id=server_id,
                old_state=old_state,
                new_state=old_state,
                tokens_delta=0,
                message=f"Server '{server_id}' is already active.",
            )

        updated = McpServerDescriptor(
            server_id=server.server_id,
            display_name=server.display_name,
            tool_names=server.tool_names,
            estimated_schema_tokens=server.estimated_schema_tokens,
            mount_state=McpServerMountState.MOUNTED_ACTIVE,
            tags=server.tags,
        )
        self._servers[server_id] = updated

        return McpMountMutationResult(
            server_id=server_id,
            old_state=old_state,
            new_state=McpServerMountState.MOUNTED_ACTIVE,
            tokens_delta=server.estimated_schema_tokens,
            message=f"Re-activated '{server.display_name}'; mounted ~{server.estimated_schema_tokens} schema tokens.",
        )

    def jit_activate_by_prompt(self, prompt: str) -> list[McpMountMutationResult]:
        """Scan user prompt for @mentions or intent keywords and re-activate hibernated servers on the fly."""
        results: list[McpMountMutationResult] = []
        lower_prompt = prompt.lower()

        for server_id, server in list(self._servers.items()):
            if server.mount_state == McpServerMountState.MOUNTED_ACTIVE:
                continue

            should_activate = False
            # 1. Exact @mention check: @jira or @figma
            mention_pattern = rf"@{re.escape(server_id.lower())}\b"
            if re.search(mention_pattern, lower_prompt):
                should_activate = True

            # 2. Tool name mentions: e.g. @jira_create_issue or tool name mention
            if not should_activate:
                for tool in server.tool_names:
                    if f"@{tool.lower()}" in lower_prompt or tool.lower() in lower_prompt:
                        should_activate = True
                        break

            # 3. Intent keyword matching
            if not should_activate and server_id.lower() in lower_prompt:
                should_activate = True

            if should_activate:
                mutation = self.wake_server(server_id)
                results.append(mutation)

        return results

    def get_all_descriptors(self) -> list[McpServerDescriptor]:
        """Return all managed MCP server descriptors."""
        return list(self._servers.values())

    def get_active_descriptors(self) -> list[McpServerDescriptor]:
        """Return descriptors currently mounted and active for LLM tool binding."""
        return [s for s in self._servers.values() if s.mount_state == McpServerMountState.MOUNTED_ACTIVE]

    def get_active_tokens(self) -> int:
        """Calculate total schema tokens currently active in tool binding."""
        return sum(s.estimated_schema_tokens for s in self.get_active_descriptors())
