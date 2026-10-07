"""Cold Start Context Profiler and On-Demand MCP Mount Suite master class.

Unifies baseline context profiling, interactive visual breakdown, and dynamic
session-level MCP hibernation with Just-In-Time prompt intent re-activation.
"""

from __future__ import annotations

from typing import Sequence

from .cold_start_profiler_engine import ColdStartContextProfilerEngine
from .cold_start_profiler_types import (
    ColdStartContextProfile,
    McpMountMutationResult,
    McpServerDescriptor,
    McpServerMountState,
)
from .on_demand_mcp_mount_manager import OnDemandMcpMountManager


class ColdStartContextProfilerAndOnDemandMcpMountSuite:
    """Master suite governing cold-start context transparency and on-demand MCP mount lifecycles."""

    def __init__(
        self,
        initial_servers: Sequence[McpServerDescriptor] | None = None,
        mcp_warning_token_threshold: int = 5000,
        mcp_warning_ratio_threshold: float = 0.40,
    ) -> None:
        self._engine = ColdStartContextProfilerEngine(
            mcp_warning_token_threshold=mcp_warning_token_threshold,
            mcp_warning_ratio_threshold=mcp_warning_ratio_threshold,
        )
        self._mount_manager = OnDemandMcpMountManager(initial_servers=initial_servers)
        self._initial_baseline_tokens = self._mount_manager.get_active_tokens()
        self._hibernations_count = 0
        self._activations_count = 0

    @property
    def engine(self) -> ColdStartContextProfilerEngine:
        """Access underlying profiling engine."""
        return self._engine

    @property
    def mount_manager(self) -> OnDemandMcpMountManager:
        """Access underlying mount manager."""
        return self._mount_manager

    def register_mcp_server(self, descriptor: McpServerDescriptor) -> None:
        """Register an external MCP server descriptor."""
        self._mount_manager.register_server(descriptor)

    def profile_session(
        self,
        session_id: str,
        system_prompt: str,
        core_tools: Sequence[dict[str, object]] | None = None,
        instruction_memory: str | None = None,
    ) -> ColdStartContextProfile:
        """Compute the current cold-start breakdown using currently mounted MCP servers."""
        return self._engine.profile_cold_start(
            session_id=session_id,
            system_prompt=system_prompt,
            core_tools=core_tools,
            mcp_servers=self._mount_manager.get_all_descriptors(),
            instruction_memory=instruction_memory,
        )

    def hibernate_server(self, server_id: str) -> McpMountMutationResult:
        """Put an active MCP server into hibernation."""
        res = self._mount_manager.hibernate_server(server_id)
        if res.tokens_delta < 0:
            self._hibernations_count += 1
        return res

    def wake_server(self, server_id: str) -> McpMountMutationResult:
        """Re-activate a sleeping MCP server."""
        res = self._mount_manager.wake_server(server_id)
        if res.tokens_delta > 0:
            self._activations_count += 1
        return res

    def preflight_scan_prompt(self, prompt: str) -> list[McpMountMutationResult]:
        """Scan user prompt before turn execution and activate hibernated tools if requested."""
        activations = self._mount_manager.jit_activate_by_prompt(prompt)
        self._activations_count += len(activations)
        return activations

    def render_context_breakdown_markdown(
        self,
        session_id: str,
        system_prompt: str,
        core_tools: Sequence[dict[str, object]] | None = None,
        instruction_memory: str | None = None,
    ) -> str:
        """Format an informative Markdown visualization of the cold-start prefill payload."""
        profile = self.profile_session(
            session_id=session_id,
            system_prompt=system_prompt,
            core_tools=core_tools,
            instruction_memory=instruction_memory,
        )
        return self._engine.render_profile_tree(profile)

    def get_token_savings_metrics(self) -> dict[str, object]:
        """Return cumulative telemetry on tokens suppressed via hibernation."""
        all_servers = self._mount_manager.get_all_descriptors()
        sleeping_servers = [s for s in all_servers if s.mount_state == McpServerMountState.SLEEPING]
        active_tokens = self._mount_manager.get_active_tokens()
        suppressed_tokens = sum(s.estimated_schema_tokens for s in sleeping_servers)
        total_possible = active_tokens + suppressed_tokens

        savings_ratio = (suppressed_tokens / total_possible) if total_possible > 0 else 0.0

        return {
            "total_managed_mcp_servers": len(all_servers),
            "currently_active_mcp_servers": len(all_servers) - len(sleeping_servers),
            "currently_sleeping_mcp_servers": len(sleeping_servers),
            "active_mcp_tokens": active_tokens,
            "suppressed_mcp_tokens": suppressed_tokens,
            "mcp_tokens_reduction_ratio": round(savings_ratio, 4),
            "hibernations_executed": self._hibernations_count,
            "jit_activations_executed": self._activations_count,
        }
