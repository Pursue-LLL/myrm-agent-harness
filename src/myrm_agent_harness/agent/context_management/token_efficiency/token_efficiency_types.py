"""Types and schemas for Provider usage anchoring and negative routing token efficiency suite.

Defines usage anchors, negative routing rules, heterogeneous reasoning seal blocks,
and token efficiency ledgers.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ProviderUsageAnchor: Authoritative token count baseline reported directly by the LLM provider API.
- NegativeRouteRule: Skill or tool metadata rule specifying negative triggers where activation is forbidden.
- NegativeRouteDecision: Evaluation result indicating whether a skill was preemptively blocked.
- ReasoningSealBlock: Encrypted or proprietary reasoning trace block bound to a specific model provider.
- TokenEfficiencyLedger: Observability ledger tracking token optimization events and efficiency savings.
- TokenEfficiencyConfig: Configuration governing provider anchoring and negative routing enforcement.

[POS]
Types and schemas for Provider usage anchoring and negative routing token efficiency suite.
"""

from dataclasses import dataclass, field
import hashlib
import time


@dataclass
class ProviderUsageAnchor:
    """Authoritative token count baseline reported directly by the LLM provider API."""

    session_id: str
    prompt_tokens: int
    last_message_fingerprint: str
    turn_index: int
    anchored_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        session_id: str,
        prompt_tokens: int,
        last_message_content: str,
        turn_index: int,
    ) -> "ProviderUsageAnchor":
        """Compute fingerprint and create usage anchor."""
        digest = hashlib.sha256(last_message_content.encode("utf-8")).hexdigest()[:16]
        return cls(
            session_id=session_id,
            prompt_tokens=prompt_tokens,
            last_message_fingerprint=digest,
            turn_index=turn_index,
        )


@dataclass
class NegativeRouteRule:
    """Skill or tool metadata rule specifying negative triggers where activation is forbidden."""

    skill_id: str
    not_for_patterns: list[str]  # e.g., ["syntax_qa", "simple_chat", "no_repo"]
    rejection_reason: str


@dataclass
class NegativeRouteDecision:
    """Evaluation result indicating whether a skill was preemptively blocked."""

    is_blocked: bool
    skill_id: str
    matched_pattern: str = ""
    reason: str = ""


@dataclass
class ReasoningSealBlock:
    """Encrypted or proprietary reasoning trace block bound to a specific model provider."""

    issuer: str  # e.g. "openai_codex", "deepseek", "anthropic"
    encrypted_payload: str
    block_id: str


@dataclass
class TokenEfficiencyLedger:
    """Observability ledger tracking token optimization events and efficiency savings."""

    session_id: str
    total_anchor_syncs: int = 0
    negative_routes_intercepted: int = 0
    seals_stripped: int = 0
    estimated_tokens_saved: int = 0
    last_updated_at: float = field(default_factory=time.time)


@dataclass
class TokenEfficiencyConfig:
    """Configuration governing provider anchoring and negative routing enforcement."""

    strict_negative_routing: bool = True
    auto_strip_heterogeneous_seals: bool = True
    bytes_per_token_estimate: float = 4.0
    fallback_negative_route_penalty: int = 1500  # Saved tokens estimate per blocked false-lane tool
