# [INPUT]: None (Pure domain contracts and types)
# [OUTPUT]: TranscriptStubRecord, HydratedTranscriptMessage, SingleFlightTokenState, DelayedSessionSlot, DynamicCredentialSpec, TranscriptResilienceConfig, compute_payload_hash
# [POS]: myrm_agent_harness.agent.context_management.transcript_resilience.resilience_types
"""Strongly-typed contracts for Transcript Offloading & Lifecycle Resilience (Item 333).

Defines out-of-viewport transcript stubs, hydrated message containers, single-flight
refresh state models, delayed concurrency slot allocations, and CLI credential specs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final
from pydantic import BaseModel, Field


class TranscriptStubRecord(BaseModel):
    """Lightweight in-memory stub representing an offloaded message out of active viewport."""

    msg_id: str = Field(..., description="Unique message identifier")
    session_id: str = Field(..., description="Owning session identifier")
    role: str = Field(..., description="Message role: user, assistant, system, tool")
    char_count: int = Field(..., description="Character count of original message content")
    has_tool_calls: bool = Field(False, description="Whether message contained tool invocations")
    original_payload_hash: str = Field(
        ..., description="SHA-256 fingerprint ensuring tamper-evident persistence"
    )
    created_at_iso: str = Field(..., description="ISO 8601 UTC timestamp of creation")


class HydratedTranscriptMessage(BaseModel):
    """Full in-memory message restored upon scrolling back into viewport."""

    msg_id: str = Field(..., description="Unique message identifier")
    session_id: str = Field(..., description="Owning session identifier")
    role: str = Field(..., description="Message role")
    content: str = Field(..., description="Full text content of message")
    tool_calls: list[dict[str, str | int | float | bool | list[str] | dict[str, str]]] = Field(
        default_factory=list, description="Tool execution call payloads"
    )
    raw_payload: str = Field(
        "", description="Optional full raw serialized JSON payload if preserved"
    )
    created_at_iso: str = Field(..., description="ISO 8601 UTC timestamp")


class SingleFlightTokenState(BaseModel):
    """Snapshot of single-flight mutex gate for high-concurrency token refresh."""

    access_token: str = Field(..., description="Active bearer access token")
    is_refreshing: bool = Field(
        False, description="True if a leader request is currently executing refresh"
    )
    pending_waiters_count: int = Field(
        0, description="Number of concurrent requests queued waiting for refresh"
    )
    last_refreshed_at_iso: str = Field(
        ..., description="UTC timestamp of the last successful token refresh"
    )


class DelayedSessionSlot(BaseModel):
    """Concurrency slot allocated only when the first actual message is dispatched."""

    session_id: str = Field(..., description="Session identifier")
    holder_name: str = Field(..., description="Agent profile or user owning the slot")
    is_claimed: bool = Field(
        False, description="True if slot has been claimed by active message dispatch"
    )
    claimed_at_iso: str = Field(
        "", description="UTC timestamp when slot was officially claimed"
    )
    tokens_consumed: int = Field(
        0, description="Cumulative tokens consumed by session while holding slot"
    )


class DynamicCredentialSpec(BaseModel):
    """Specification for securely resolving API credentials from an external CLI vault."""

    command_args: list[str] = Field(
        ..., description="Command and arguments to execute (e.g. ['pass', 'show', 'api_key'])"
    )
    env_vars: dict[str, str] = Field(
        default_factory=dict, description="Environment variables passed to child subprocess"
    )
    timeout_seconds: float = Field(
        10.0, description="Hard timeout in seconds to prevent subprocess hangs"
    )
    cache_ttl_seconds: float = Field(
        300.0, description="Memory cache TTL in seconds for evaluated credential"
    )


class TranscriptResilienceConfig(BaseModel):
    """Configuration governing transcript offloading, refresh mutex, and slot limits."""

    max_viewport_messages: int = Field(
        100, description="Number of recent messages preserved fully in active memory"
    )
    single_flight_timeout_seconds: float = Field(
        8.0, description="Hard timeout for leader refresh before triggering emergency trip"
    )
    max_concurrency_slots: int = Field(
        10, description="Maximum total concurrent claimed session slots"
    )
    max_stub_records_per_session: int = Field(
        5000, description="Maximum stubs retained in memory per long-running session"
    )


def compute_payload_hash(
    role: str,
    content: str,
    tool_calls: list[dict[str, str | int | float | bool | list[str] | dict[str, str]]] | None = None,
) -> str:
    """Compute deterministic SHA-256 fingerprint for a message payload."""
    calls_str = json.dumps(tool_calls or [], sort_keys=True, ensure_ascii=False)
    raw = f"{role}::{content}::{calls_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


DEFAULT_MAX_VIEWPORT_MESSAGES: Final[int] = 100
DEFAULT_REFRESH_TIMEOUT_SECONDS: Final[float] = 8.0
DEFAULT_MAX_CONCURRENCY_SLOTS: Final[int] = 10
