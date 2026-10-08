"""Three-Tier Stacked Policy Stack evaluating Session, Agent, and Server policies."""

from __future__ import annotations

import fnmatch

from .types import (
    AskCardPayload,
    LifecyclePhase,
    PolicyEvaluationResult,
    PolicyRule,
)


class ThreeTierStackedPolicyStack:
    """Orchestrates declarative policy evaluation across Session, Agent, and Server tiers.

    Evaluation precedence:
    1. Session tier (highest priority, dynamically injected by user, can short-circuit).
    2. Agent tier (agent configuration specification).
    3. Server tier (hard enterprise/infrastructure baseline).
    """

    def __init__(self) -> None:
        self._server_rules: list[PolicyRule] = []
        self._agent_rules: dict[str, list[PolicyRule]] = {}  # agent_id -> rules
        self._session_rules: dict[str, list[PolicyRule]] = {}  # session_id -> rules

    def add_server_rule(self, rule: PolicyRule) -> None:
        """Register organization/server baseline rule."""
        self._server_rules.append(rule)

    def add_agent_rule(self, rule: PolicyRule) -> None:
        """Register agent-spec policy rule."""
        agent_key = (rule.agent_id or "*").strip()
        if agent_key not in self._agent_rules:
            self._agent_rules[agent_key] = []
        self._agent_rules[agent_key].append(rule)

    def add_session_rule(self, rule: PolicyRule) -> None:
        """Register session-level dynamic policy rule."""
        session_key = (rule.session_id or "*").strip()
        if session_key not in self._session_rules:
            self._session_rules[session_key] = []
        self._session_rules[session_key].append(rule)

    def clear_session_rules(self, session_id: str) -> None:
        """Clear dynamic rules for a concluded session."""
        self._session_rules.pop(session_id.strip(), None)

    def _match_rule(
        self,
        rule: PolicyRule,
        phase: LifecyclePhase,
        target: str,
    ) -> bool:
        """Test if rule matches lifecycle phase and target pattern."""
        if rule.phase != phase:
            return False
        return fnmatch.fnmatch(target.strip().lower(), rule.target_pattern.strip().lower())

    def evaluate(
        self,
        phase: LifecyclePhase,
        target: str,
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> PolicyEvaluationResult:
        """Evaluate invocation against stacked tiers with fast short-circuiting."""
        clean_target = target.strip()
        pending_ask_card: AskCardPayload | None = None
        matched_ask_tier: str | None = None
        matched_ask_rule: str | None = None
        ask_reason: str = ""

        # Tier 1: Session level (Highest priority)
        if session_id:
            sess_rules = self._session_rules.get(session_id.strip(), [])
            for rule in sess_rules:
                if self._match_rule(rule, phase, clean_target):
                    if rule.action == "deny":
                        return PolicyEvaluationResult(
                            decision="deny",
                            matched_tier="session",
                            matched_rule=rule.name,
                            reason=f"Session policy denied: {rule.reason}",
                            requires_approval=False,
                        )
                    if rule.action == "ask":
                        pending_ask_card = AskCardPayload(
                            prompt_title=f"Session Approval: {rule.name}",
                            target_operation=clean_target,
                            risk_level="medium",
                            recommended_action="ask",
                            context_summary=rule.reason,
                        )
                        matched_ask_tier = "session"
                        matched_ask_rule = rule.name
                        ask_reason = rule.reason

        # Tier 2: Agent spec level
        if agent_id:
            agent_rules = self._agent_rules.get(agent_id.strip(), []) + self._agent_rules.get("*", [])
            for rule in agent_rules:
                if self._match_rule(rule, phase, clean_target):
                    if rule.action == "deny":
                        return PolicyEvaluationResult(
                            decision="deny",
                            matched_tier="agent",
                            matched_rule=rule.name,
                            reason=f"Agent specification policy denied: {rule.reason}",
                            requires_approval=False,
                        )
                    if rule.action == "ask" and pending_ask_card is None:
                        pending_ask_card = AskCardPayload(
                            prompt_title=f"Agent Specification Approval: {rule.name}",
                            target_operation=clean_target,
                            risk_level="high",
                            recommended_action="ask",
                            context_summary=rule.reason,
                        )
                        matched_ask_tier = "agent"
                        matched_ask_rule = rule.name
                        ask_reason = rule.reason

        # Tier 3: Server enterprise baseline level (Lowest priority, hard fallback)
        for rule in self._server_rules:
            if self._match_rule(rule, phase, clean_target):
                if rule.action == "deny":
                    return PolicyEvaluationResult(
                        decision="deny",
                        matched_tier="server",
                        matched_rule=rule.name,
                        reason=f"Server enterprise baseline policy denied: {rule.reason}",
                        requires_approval=False,
                    )
                if rule.action == "ask" and pending_ask_card is None:
                    pending_ask_card = AskCardPayload(
                        prompt_title=f"Enterprise Baseline Approval: {rule.name}",
                        target_operation=clean_target,
                        risk_level="critical",
                        recommended_action="ask",
                        context_summary=rule.reason,
                    )
                    matched_ask_tier = "server"
                    matched_ask_rule = rule.name
                    ask_reason = rule.reason

        # If any tier produced an ASK decision and no higher tier denied
        if pending_ask_card is not None:
            return PolicyEvaluationResult(
                decision="ask",
                matched_tier=matched_ask_tier,  # type: ignore[arg-type]
                matched_rule=matched_ask_rule,
                reason=f"Policy requires interactive user confirmation: {ask_reason}",
                requires_approval=True,
                ask_card=pending_ask_card,
            )

        return PolicyEvaluationResult(
            decision="allow",
            matched_tier=None,
            matched_rule=None,
            reason="Operation permitted under all stacked policy tiers.",
            requires_approval=False,
        )
