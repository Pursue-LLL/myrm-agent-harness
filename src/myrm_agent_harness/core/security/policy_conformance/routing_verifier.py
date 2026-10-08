"""
[POS] src/myrm_agent_harness/core/security/policy_conformance/routing_verifier.py
[INPUT] types
[OUTPUT] SyntheticMessageRoutingVerifier
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .types import (
    RoutingRule,
    RoutingTestCase,
    RoutingVerificationResult,
)

logger = logging.getLogger(__name__)


class SyntheticMessageRoutingVerifier:
    """Performs deterministic zero-cost semantic message routing assertions."""

    def __init__(self, rules: tuple[RoutingRule, ...] | None = None) -> None:
        self._rules: list[RoutingRule] = list(rules or ())

    def register_rule(self, rule: RoutingRule) -> None:
        """Register or update a semantic routing rule for an agent."""
        self._rules = [r for r in self._rules if r.agent_id != rule.agent_id]
        self._rules.append(rule)
        logger.info("Registered routing rule for agent: %s", rule.agent_id)

    def verify_case(self, case: RoutingTestCase) -> RoutingVerificationResult:
        """Verify if a representative synthetic message routes accurately to the expected agent."""
        if not self._rules:
            return RoutingVerificationResult(
                case_id=case.case_id,
                is_matched=False,
                expected_agent_id=case.expected_agent_id,
                routed_agent_id="none",
                confidence_score=0.0,
                diagnostic="No routing rules registered in verification suite",
            )

        query_lower = case.sample_message.strip().lower()

        # Check required keywords constraint if declared
        for kw in case.required_keywords:
            if kw.strip().lower() not in query_lower:
                return RoutingVerificationResult(
                    case_id=case.case_id,
                    is_matched=False,
                    expected_agent_id=case.expected_agent_id,
                    routed_agent_id="none",
                    confidence_score=0.0,
                    diagnostic=f"Required test keyword '{kw}' missing from sample message",
                )

        best_agent_id = "default_agent"
        best_score = 0.0

        for rule in self._rules:
            score = 0.0
            # Keyword matching
            for kw in rule.keywords:
                if kw.strip().lower() in query_lower:
                    score += 1.0
            # Intent tag matching
            for tag in rule.intent_tags:
                if tag.strip().lower() in query_lower:
                    score += 1.5

            if score > best_score:
                best_score = score
                best_agent_id = rule.agent_id

        # Normalize confidence to [0.0, 1.0]
        confidence = min(1.0, best_score / 3.0) if best_score > 0 else 0.1
        is_matched = best_agent_id.strip().lower() == case.expected_agent_id.strip().lower()

        diagnostic = (
            f"Routing asserted successfully to '{best_agent_id}' (confidence: {confidence:.2f})"
            if is_matched
            else (
                f"Routing drift detected: expected '{case.expected_agent_id}', "
                f"but routed to '{best_agent_id}' (confidence: {confidence:.2f})"
            )
        )

        return RoutingVerificationResult(
            case_id=case.case_id,
            is_matched=is_matched,
            expected_agent_id=case.expected_agent_id,
            routed_agent_id=best_agent_id,
            confidence_score=confidence,
            diagnostic=diagnostic,
        )

    def verify_suite(
        self, test_cases: tuple[RoutingTestCase, ...]
    ) -> tuple[RoutingVerificationResult, ...]:
        """Run all synthetic test cases in batch."""
        return tuple(self.verify_case(c) for c in test_cases)

    @staticmethod
    def calculate_pass_rate(
        results: tuple[RoutingVerificationResult, ...]
    ) -> float:
        """Calculate percentage pass rate across verification cases."""
        if not results:
            return 100.0
        passed = sum(1 for r in results if r.is_matched)
        return (passed / len(results)) * 100.0
