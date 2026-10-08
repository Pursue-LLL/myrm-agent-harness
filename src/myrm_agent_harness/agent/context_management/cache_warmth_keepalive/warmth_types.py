# [INPUT]: None (Pure domain types and contracts)
# [OUTPUT]: CacheWarmthState, CacheProviderType, ProviderCacheSpec, WarmthCountdownMetrics, HeartbeatProbeConfig, HeartbeatProbeDecision, HeartbeatExecutionRecord
# [POS]: myrm_agent_harness.agent.context_management.cache_warmth_keepalive.warmth_types
"""Strongly-typed contracts for Context Cache Warmth Gauge and Keep-Alive Suite (Item 328).

Defines warmth states, multi-provider cache specifications, countdown metrics,
and heartbeat keep-alive probe decision records.
"""

from __future__ import annotations

from enum import Enum
from typing import Final
from pydantic import BaseModel, Field


class CacheWarmthState(str, Enum):
    """Categorical warmth state of context prompt caching."""

    WARM = "warm"
    COOLING_CRITICAL = "cooling_critical"
    COLD = "cold"
    DISABLED = "disabled"


class CacheProviderType(str, Enum):
    """Supported LLM providers with prompt caching semantics."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    GENERIC = "generic"


class ProviderCacheSpec(BaseModel):
    """Cache specification parameters for a specific provider/model."""

    provider_type: CacheProviderType = Field(
        ..., description="Provider classification for prompt caching"
    )
    default_ttl_seconds: int = Field(
        300, description="Default cache time-to-live in seconds (e.g. 5m)"
    )
    extended_ttl_seconds: int = Field(
        3600, description="Extended cache time-to-live in seconds (e.g. 1h for Anthropic direct)"
    )
    critical_threshold_seconds: int = Field(
        120, description="Time threshold before expiry to enter cooling_critical state (seconds)"
    )
    min_tokens_for_cache: int = Field(
        1024, description="Minimum tokens required before provider enables caching"
    )
    supports_explicit_keepalive: bool = Field(
        True, description="Whether this provider supports explicit lightweight keepalive probes"
    )
    input_cost_per_m: float = Field(
        3.0, description="Standard input token cost in USD per 1M tokens"
    )
    cache_write_cost_per_m: float = Field(
        3.75, description="Cache creation/write input token cost in USD per 1M tokens"
    )
    cache_read_cost_per_m: float = Field(
        0.30, description="Cache hit/read input token cost in USD per 1M tokens"
    )
    cache_savings_ratio: float = Field(
        0.90, description="Theoretical cost savings ratio on cache hit (e.g. 0.90 = 90% savings)"
    )


class WarmthCountdownMetrics(BaseModel):
    """Live telemetry and countdown metrics for session cache warmth."""

    session_id: str = Field(..., description="Unique conversation session identifier")
    state: CacheWarmthState = Field(..., description="Current cache warmth lifecycle state")
    remaining_seconds: float = Field(
        ..., description="Remaining seconds until cache expiration (0 if cold)"
    )
    total_ttl_seconds: int = Field(
        ..., description="Total effective TTL granted in seconds"
    )
    warmth_ratio: float = Field(
        ..., description="Remaining warmth ratio between 0.0 (cold) and 1.0 (freshly warm)"
    )
    cached_tokens: int = Field(
        ..., description="Number of tokens currently preserved in context cache"
    )
    expires_at_iso: str = Field(
        ..., description="ISO 8601 UTC timestamp of cache expiration"
    )
    last_active_at_iso: str = Field(
        ..., description="ISO 8601 UTC timestamp of last cache renewal or interaction"
    )
    estimated_hit_rate: float = Field(
        ..., description="Estimated cache hit rate (0.0 to 1.0)"
    )
    cumulative_tokens_saved: int = Field(
        0, description="Total tokens saved across turns in this session"
    )
    cumulative_cost_saved_usd: float = Field(
        0.0, description="Total USD saved across turns due to cache hits"
    )
    badge_text: str = Field(
        ..., description="Human-readable status label for UI capsule (e.g. '🔥 缓存保温中（剩余 48 分钟）')"
    )
    badge_color: str = Field(
        ..., description="Semantic color for UI indicator ('green' | 'amber' | 'gray')"
    )
    is_keepalive_eligible: bool = Field(
        ..., description="Whether this session is a candidate for keep-alive probing"
    )


class HeartbeatProbeConfig(BaseModel):
    """Governance configuration for automatic keep-alive heartbeat probes."""

    enabled: bool = Field(
        True, description="Master switch for automated keep-alive probes"
    )
    min_tokens_threshold: int = Field(
        1024, description="Minimum cached tokens required to trigger keep-alive"
    )
    critical_window_seconds: int = Field(
        120, description="Seconds before expiry during which keep-alive is triggered"
    )
    max_consecutive_heartbeats: int = Field(
        3, description="Maximum number of consecutive automatic heartbeats without user interaction"
    )
    max_idle_seconds: int = Field(
        14400, description="Maximum session idle seconds allowed before giving up (default: 4 hours)"
    )
    probe_max_tokens: int = Field(
        1, description="Maximum completion tokens requested for the silent ping probe"
    )


class HeartbeatProbeDecision(BaseModel):
    """Evaluation verdict for whether a keep-alive probe should be dispatched."""

    should_probe: bool = Field(
        ..., description="True if a silent keep-alive probe must be dispatched"
    )
    reason: str = Field(
        ..., description="Detailed explanation for the decision"
    )
    session_id: str = Field(
        ..., description="Target session identifier"
    )
    probe_token_budget: int = Field(
        1, description="Maximum tokens budgeted for the silent probe"
    )
    suggested_probe_prompt: str = Field(
        "keep-alive ping", description="Payload prompt to maintain cached prefix warmth"
    )
    target_ttl_renewal_seconds: int = Field(
        3600, description="Expected TTL extension after successful probe"
    )


class HeartbeatExecutionRecord(BaseModel):
    """Audit record of a completed keep-alive probe."""

    session_id: str = Field(..., description="Target session identifier")
    executed_at_iso: str = Field(..., description="Execution timestamp")
    probe_tokens: int = Field(1, description="Tokens consumed by the probe")
    renewed_ttl_seconds: int = Field(..., description="New TTL duration granted")
    estimated_probe_cost_usd: float = Field(..., description="Micro-cost incurred by probe")
    consecutive_heartbeat_index: int = Field(..., description="Sequential index of heartbeat")


DEFAULT_PROBE_PROMPT: Final[str] = "ping"
