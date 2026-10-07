"""Engine for Provider usage anchoring, negative routing, and seal stripping.

Provides authoritative usage anchor synchronization, zero-millisecond negative routing
interceptions for false-lane skills, and seamless stripping of heterogeneous reasoning seals.
"""

import copy
import hashlib
import logging
import re
from typing import Optional

from .token_efficiency_types import (
    NegativeRouteDecision,
    NegativeRouteRule,
    ProviderUsageAnchor,
    TokenEfficiencyConfig,
    TokenEfficiencyLedger,
)

logger = logging.getLogger(__name__)


class TokenEfficiencyGovernorEngine:
    """Core governor for token efficiency optimizations and cross-vendor resilience."""

    def __init__(self, config: Optional[TokenEfficiencyConfig] = None) -> None:
        self.config = config or TokenEfficiencyConfig()
        self._anchors: dict[str, ProviderUsageAnchor] = {}
        self._ledgers: dict[str, TokenEfficiencyLedger] = {}

    def record_provider_anchor(
        self,
        session_id: str,
        prompt_tokens: int,
        last_message_content: str,
        turn_index: int,
    ) -> ProviderUsageAnchor:
        """Record the authoritative prompt token count from Provider API response."""
        anchor = ProviderUsageAnchor.create(
            session_id=session_id,
            prompt_tokens=prompt_tokens,
            last_message_content=last_message_content,
            turn_index=turn_index,
        )
        self._anchors[session_id] = anchor

        ledger = self._ledgers.setdefault(session_id, TokenEfficiencyLedger(session_id=session_id))
        ledger.total_anchor_syncs += 1
        logger.info(
            "Anchored session %s at turn %d: %d tokens (fp=%s)",
            session_id,
            turn_index,
            prompt_tokens,
            anchor.last_message_fingerprint,
        )
        return anchor

    def get_anchor(self, session_id: str) -> Optional[ProviderUsageAnchor]:
        """Fetch current registered provider usage anchor for session."""
        return self._anchors.get(session_id)

    def calculate_anchored_context_tokens(
        self,
        session_id: str,
        incremental_messages: list[dict[str, str]],
        base_message_content: str,
    ) -> int:
        """Compute context tokens by combining authoritative anchor baseline with incremental messages."""
        anchor = self._anchors.get(session_id)
        if not anchor:
            # Fallback to local heuristic estimation if no anchor exists yet
            total_chars = sum(len(m.get("content", "")) for m in incremental_messages)
            return max(1, int(total_chars / self.config.bytes_per_token_estimate))

        # Check fingerprint match for anchor baseline
        current_fp = hashlib.sha256(base_message_content.encode("utf-8")).hexdigest()[:16]
        if current_fp != anchor.last_message_fingerprint:
            # Anchor fingerprint mismatch; calculate fresh estimate
            total_chars = len(base_message_content) + sum(len(m.get("content", "")) for m in incremental_messages)
            return max(1, int(total_chars / self.config.bytes_per_token_estimate))

        # Baseline matched: compute solely the incremental tokens on top of authoritative baseline
        inc_chars = sum(len(m.get("content", "")) for m in incremental_messages)
        inc_tokens = int(inc_chars / self.config.bytes_per_token_estimate)
        return anchor.prompt_tokens + inc_tokens

    def evaluate_negative_routes(
        self,
        session_id: str,
        user_intent: str,
        candidate_skills: list[str],
        rules: list[NegativeRouteRule],
    ) -> tuple[list[str], list[NegativeRouteDecision]]:
        """Intercept skills whose NOT FOR negative patterns match user intent to avoid false-lane tool loops."""
        rule_map = {r.skill_id: r for r in rules}
        allowed_skills: list[str] = []
        decisions: list[NegativeRouteDecision] = []
        intent_lower = user_intent.lower()

        ledger = self._ledgers.setdefault(session_id, TokenEfficiencyLedger(session_id=session_id))

        for skill_id in candidate_skills:
            rule = rule_map.get(skill_id)
            if not rule:
                allowed_skills.append(skill_id)
                decisions.append(NegativeRouteDecision(is_blocked=False, skill_id=skill_id))
                continue

            # Check if any NOT FOR pattern triggers
            matched_pat = ""
            for pat in rule.not_for_patterns:
                if pat.lower() in intent_lower:
                    matched_pat = pat
                    break

            if matched_pat:
                decisions.append(
                    NegativeRouteDecision(
                        is_blocked=True,
                        skill_id=skill_id,
                        matched_pattern=matched_pat,
                        reason=f"Blocked by NOT FOR pattern '{matched_pat}': {rule.rejection_reason}",
                    )
                )
                ledger.negative_routes_intercepted += 1
                ledger.estimated_tokens_saved += self.config.fallback_negative_route_penalty
                logger.info("Preemptively blocked skill %s for intent via NOT FOR '%s'", skill_id, matched_pat)
            else:
                allowed_skills.append(skill_id)
                decisions.append(NegativeRouteDecision(is_blocked=False, skill_id=skill_id))

        return allowed_skills, decisions

    def strip_incompatible_reasoning_seals(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        target_provider: str,
    ) -> tuple[list[dict[str, str]], int]:
        """Strip encrypted or proprietary reasoning seal tags when target provider does not match issuer."""
        sanitized_messages: list[dict[str, str]] = []
        stripped_count = 0
        seal_pattern = r"\[encrypted_reasoning\s+issuer=[\"'](.*?)[\"']\](.*?)\[/encrypted_reasoning\]"

        for msg in messages:
            msg_copy = copy.deepcopy(msg)
            content = msg_copy.get("content", "")

            matches = list(re.finditer(seal_pattern, content, flags=re.DOTALL))
            if matches:
                def replace_seal(match: re.Match[str]) -> str:
                    nonlocal stripped_count
                    issuer = match.group(1).strip()
                    if issuer != target_provider:
                        stripped_count += 1
                        return ""  # Seamlessly strip incompatible seal
                    return match.group(0)

                sanitized_content = re.sub(seal_pattern, replace_seal, content, flags=re.DOTALL)
                msg_copy["content"] = sanitized_content.strip()

            sanitized_messages.append(msg_copy)

        if stripped_count > 0:
            ledger = self._ledgers.setdefault(session_id, TokenEfficiencyLedger(session_id=session_id))
            ledger.seals_stripped += stripped_count
            logger.info("Stripped %d incompatible reasoning seals for target provider %s", stripped_count, target_provider)

        return sanitized_messages, stripped_count

    def get_ledger(self, session_id: str) -> TokenEfficiencyLedger:
        """Fetch complete observability ledger for the session."""
        return self._ledgers.setdefault(session_id, TokenEfficiencyLedger(session_id=session_id))
