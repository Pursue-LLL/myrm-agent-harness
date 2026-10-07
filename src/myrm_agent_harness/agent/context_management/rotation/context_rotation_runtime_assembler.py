# ============================================================================
# ContextRotationRuntimeAssembler (Item 155)
# Production-grade 3-tier runtime configuration assembler and config-hashed
# MCP persistent connection pool for zero-reconnect context rotations.
# ============================================================================

from __future__ import annotations

import hashlib
import logging
import time

from .assembly_types import (
    ApprovalMode,
    AssembledRuntimeContext,
    LiveSecurityConfig,
    McpPoolReconcileResult,
    McpServerConfig,
    SoftBudgetConfig,
    StrictPrefixConfig,
    ThinkingLevel,
)

logger = logging.getLogger(__name__)


class RuntimeAssemblyError(RuntimeError):
    """Raised when runtime assembly encounters corrupted configuration (Fail-Loud)."""


class ContextRotationRuntimeAssembler:
    """Orchestrates three-tier runtime parameter assembly and MCP connection caching."""

    def __init__(self) -> None:
        self._current_context: AssembledRuntimeContext | None = None
        self._mcp_cached_hashes: dict[str, str] = {}
        self._mcp_reconnect_counts: dict[str, int] = {}
        self._previous_thinking_level: ThinkingLevel | None = None

    def _compute_prefix_hash(
        self,
        system_prompt: str,
        model_name: str,
        tool_signatures: tuple[str, ...],
    ) -> str:
        """Computes deterministic SHA-256 hash for strict prefix prompt caching."""
        sigs = ",".join(sorted(tool_signatures))
        raw = f"{system_prompt}::{model_name}::{sigs}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _reconcile_mcp_pool(
        self,
        new_configs: list[McpServerConfig],
    ) -> McpPoolReconcileResult:
        """Reconciles live MCP connections using config hash comparison."""
        new_server_map: dict[str, McpServerConfig] = {}
        for cfg in new_configs:
            if cfg.server_id in new_server_map:
                raise RuntimeAssemblyError(f"Duplicate MCP server ID in configuration: {cfg.server_id}")
            new_server_map[cfg.server_id] = cfg

        reused: list[str] = []
        reconnected: list[str] = []
        disconnected: list[str] = []

        current_cached_ids = set(self._mcp_cached_hashes.keys())
        new_ids = set(new_server_map.keys())

        # Detect disconnected servers
        for dead_id in current_cached_ids - new_ids:
            disconnected.append(dead_id)
            self._mcp_cached_hashes.pop(dead_id, None)

        # Reconcile existing and incoming servers
        for s_id, s_cfg in new_server_map.items():
            new_hash = s_cfg.compute_config_hash()
            old_hash = self._mcp_cached_hashes.get(s_id)

            if old_hash is not None and old_hash == new_hash:
                # Configuration unchanged: 0-reconnect reuse!
                reused.append(s_id)
            else:
                # New or modified configuration: reconnect & refresh
                reconnected.append(s_id)
                self._mcp_cached_hashes[s_id] = new_hash
                self._mcp_reconnect_counts[s_id] = self._mcp_reconnect_counts.get(s_id, 0) + 1

        return McpPoolReconcileResult(
            reused_servers=reused,
            reconnected_servers=reconnected,
            disconnected_servers=disconnected,
        )

    def assemble_on_rotation(
        self,
        context_id: str,
        system_prompt: str,
        model_name: str,
        tool_signatures: tuple[str, ...],
        thinking_level: ThinkingLevel,
        mcp_configs: list[McpServerConfig],
        approval_mode: ApprovalMode = ApprovalMode.ASK_FIRST,
        allowed_tool_names: frozenset[str] | None = None,
        denied_tool_names: frozenset[str] | None = None,
        max_reasoning_tokens: int = 4096,
        is_context_rotation: bool = True,
    ) -> AssembledRuntimeContext:
        """Assembles a new runtime context adhering strictly to the three-tier rule."""
        # Fail-Loud Validation
        if not context_id or not context_id.strip():
            raise RuntimeAssemblyError("Assembly failed: context_id cannot be blank.")
        if not system_prompt or not system_prompt.strip():
            raise RuntimeAssemblyError("Assembly failed: system_prompt cannot be blank.")
        if not model_name or not model_name.strip():
            raise RuntimeAssemblyError("Assembly failed: model_name cannot be blank.")

        # Tier 1: Strict Prefix Assembly (Prompt Cache Invariant)
        prefix_hash = self._compute_prefix_hash(system_prompt, model_name, tool_signatures)
        strict_prefix = StrictPrefixConfig(
            system_prompt=system_prompt,
            model_name=model_name,
            tool_signatures=tool_signatures,
            prefix_hash=prefix_hash,
        )

        # Tier 2: Soft Budget Assembly (Reasoning Level Shift Gate)
        suggest_compaction = False
        warning_note = ""
        if (
            not is_context_rotation
            and self._previous_thinking_level is not None
            and self._previous_thinking_level != thinking_level
        ):
            suggest_compaction = True
            warning_note = (
                f"Thinking level shifted from {self._previous_thinking_level} to {thinking_level} "
                "mid-context. It is strongly advised to trigger context compaction to prevent "
                "Provider prompt cache disruption."
            )
            logger.warning(warning_note)

        self._previous_thinking_level = thinking_level

        soft_budget = SoftBudgetConfig(
            thinking_level=thinking_level,
            max_reasoning_tokens=max_reasoning_tokens,
            suggest_compaction_before_shift=suggest_compaction,
            warning_note=warning_note,
        )

        # Tier 3: Live Security Gate (Real-time dynamic decision)
        live_security = LiveSecurityConfig(
            approval_mode=approval_mode,
            allowed_tool_names=allowed_tool_names or frozenset(),
            denied_tool_names=denied_tool_names or frozenset(),
            evaluated_at=time.time(),
        )

        # Config-Hashed MCP Pool Reconciliation
        mcp_status = self._reconcile_mcp_pool(mcp_configs)

        assembled = AssembledRuntimeContext(
            context_id=context_id,
            strict_prefix=strict_prefix,
            soft_budget=soft_budget,
            live_security=live_security,
            mcp_pool_status=mcp_status,
            assembled_at=time.time(),
        )

        self._current_context = assembled
        return assembled

    def get_current_context(self) -> AssembledRuntimeContext | None:
        """Retrieves the currently assembled active runtime context."""
        return self._current_context

    def get_mcp_reconnection_count(self, server_id: str) -> int:
        """Retrieves how many times a given MCP server has undergone reconnection."""
        return self._mcp_reconnect_counts.get(server_id, 0)
