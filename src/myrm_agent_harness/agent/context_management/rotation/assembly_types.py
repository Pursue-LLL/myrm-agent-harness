# ============================================================================
# Three-Tier Context Assembly & MCP Reuse Types (Item 155)
# Strict typed contracts for per-context three-tier runtime parameters
# (Strict prefix invariant, Soft thinking budget, Live security gates)
# and config-hashed persistent MCP connection reuse.
# ============================================================================

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import StrEnum


class ThinkingLevel(StrEnum):
    """Reasoning effort budget governing the model's internal thinking."""

    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalMode(StrEnum):
    """Live interactive approval mode evaluated dynamically per tool execution."""

    AUTO = "auto"
    ASK_FIRST = "ask_first"
    DENY = "deny"


class McpConnectionStatus(StrEnum):
    """Lifecycle status of a managed MCP server connection across rotation."""

    REUSED = "reused"
    RECONNECTED = "reconnected"
    DISCONNECTED = "disconnected"


@dataclass(slots=True, frozen=True)
class StrictPrefixConfig:
    """Strict tier: Frozen request prefix guaranteeing 100% Provider Prompt Cache hits."""

    system_prompt: str
    model_name: str
    tool_signatures: tuple[str, ...] = field(default_factory=tuple)
    prefix_hash: str = ""

    def to_dict(self) -> dict[str, str | list[str]]:
        """Serializes strict prefix config to dictionary."""
        return {
            "system_prompt": self.system_prompt,
            "model_name": self.model_name,
            "tool_signatures": list(self.tool_signatures),
            "prefix_hash": self.prefix_hash,
        }


@dataclass(slots=True)
class SoftBudgetConfig:
    """Soft tier: Dynamic reasoning budget with cache disruption warning gates."""

    thinking_level: ThinkingLevel
    max_reasoning_tokens: int = 4096
    suggest_compaction_before_shift: bool = False
    warning_note: str = ""

    def to_dict(self) -> dict[str, str | int | bool]:
        """Serializes soft budget config to dictionary."""
        return {
            "thinking_level": str(self.thinking_level),
            "max_reasoning_tokens": self.max_reasoning_tokens,
            "suggest_compaction_before_shift": self.suggest_compaction_before_shift,
            "warning_note": self.warning_note,
        }


@dataclass(slots=True)
class LiveSecurityConfig:
    """Live tier: Instant security policy and per-action tool approval permissions."""

    approval_mode: ApprovalMode
    allowed_tool_names: frozenset[str] = field(default_factory=frozenset)
    denied_tool_names: frozenset[str] = field(default_factory=frozenset)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | list[str] | float]:
        """Serializes live security config to dictionary."""
        return {
            "approval_mode": str(self.approval_mode),
            "allowed_tool_names": sorted(self.allowed_tool_names),
            "denied_tool_names": sorted(self.denied_tool_names),
            "evaluated_at": self.evaluated_at,
        }


@dataclass(slots=True, frozen=True)
class McpServerConfig:
    """Configuration descriptor for an external MCP server connection."""

    server_id: str
    command_or_url: str
    env_vars: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    tools_whitelist: tuple[str, ...] = field(default_factory=tuple)

    def compute_config_hash(self) -> str:
        """Computes deterministic SHA-256 fingerprint for cache key matching."""
        env_str = ",".join(f"{k}={v}" for k, v in sorted(self.env_vars))
        tools_str = ",".join(sorted(self.tools_whitelist))
        raw = f"{self.server_id}::{self.command_or_url}::{env_str}::{tools_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, str | list[str] | list[list[str]]]:
        """Serializes MCP server config to dictionary."""
        return {
            "server_id": self.server_id,
            "command_or_url": self.command_or_url,
            "env_vars": [list(item) for item in self.env_vars],
            "tools_whitelist": list(self.tools_whitelist),
            "config_hash": self.compute_config_hash(),
        }


@dataclass(slots=True)
class McpPoolReconcileResult:
    """Outcome of reconciling MCP connection pool against updated server configs."""

    reused_servers: list[str] = field(default_factory=list)
    reconnected_servers: list[str] = field(default_factory=list)
    disconnected_servers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        """Serializes reconcile result to dictionary."""
        return {
            "reused_servers": list(self.reused_servers),
            "reconnected_servers": list(self.reconnected_servers),
            "disconnected_servers": list(self.disconnected_servers),
        }


@dataclass(slots=True)
class AssembledRuntimeContext:
    """Complete per-context runtime artifact assembled at rotation boundaries."""

    context_id: str
    strict_prefix: StrictPrefixConfig
    soft_budget: SoftBudgetConfig
    live_security: LiveSecurityConfig
    mcp_pool_status: McpPoolReconcileResult
    assembled_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes assembled runtime context to dictionary."""
        return {
            "context_id": self.context_id,
            "strict_prefix": self.strict_prefix.to_dict(),
            "soft_budget": self.soft_budget.to_dict(),
            "live_security": self.live_security.to_dict(),
            "mcp_pool_status": self.mcp_pool_status.to_dict(),
            "assembled_at": self.assembled_at,
        }
