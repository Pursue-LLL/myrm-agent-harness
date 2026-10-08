"""Tier 2: Triggered Context Router for path and intent-scoped domain rules.

[INPUT]
- FourTierContextConfig, TriggerDomainKind, TriggeredRule from four_tier_types.

[OUTPUT]
- TriggeredContextRouter: Dynamically matches specialized domain guidelines based on targeted files
  and intent keywords, injecting rules JIT and discarding them when irrelevant.

[POS]
Router eliminating static rule stuffing and context rot by dispatching rules conditionally.
"""

from __future__ import annotations

import fnmatch
from typing import Dict, List, Sequence

from .four_tier_types import (
    FourTierContextConfig,
    TriggerDomainKind,
    TriggeredRule,
)


class TriggeredContextRouter:
    """Evaluates targets and query intents against specialized domain rules."""

    def __init__(self, config: FourTierContextConfig | None = None) -> None:
        self._config = config or FourTierContextConfig()
        self._rules: List[TriggeredRule] = []
        self._register_default_rules()

    @property
    def config(self) -> FourTierContextConfig:
        return self._config

    def _register_default_rules(self) -> None:
        """Register canonical enterprise domain rules across core disciplines."""
        self.register_rule(
            TriggeredRule(
                rule_id="rule_db_discipline",
                domain=TriggerDomainKind.DATABASE,
                path_patterns=["*db*", "*sql*", "*migration*", "*models*", "*schema*"],
                keyword_patterns=["database", "sql", "query", "transaction", "migration", "table"],
                content=(
                    "DATABASE DISCIPLINE: Always use parameterized queries; never construct raw SQL strings. "
                    "Ensure explicit ACID transaction boundaries and composite index coverage on foreign keys. "
                    "Prohibit unbounded SELECT *; always specify pagination."
                ),
                priority=100,
            )
        )
        self.register_rule(
            TriggeredRule(
                rule_id="rule_api_contract",
                domain=TriggerDomainKind.API_CONTRACT,
                path_patterns=["*api*", "*route*", "*endpoint*", "*controller*", "*openapi*"],
                keyword_patterns=["api", "rest", "endpoint", "fastapi", "route", "http"],
                content=(
                    "API CONTRACT DISCIPLINE: Enforce strict Pydantic/Zod request & response schemas (zero Any). "
                    "All mutation endpoints must declare idempotency keys. Return canonical RFC 7807 problem details on failure."
                ),
                priority=90,
            )
        )
        self.register_rule(
            TriggeredRule(
                rule_id="rule_payment_billing",
                domain=TriggerDomainKind.PAYMENT_BILLING,
                path_patterns=["*payment*", "*billing*", "*invoice*", "*checkout*", "*subscription*"],
                keyword_patterns=["payment", "billing", "invoice", "refund", "charge", "stripe", "money"],
                content=(
                    "FINANCIAL SAFETY DISCIPLINE: Never retry payment calls without verifying ledger idempotency. "
                    "All monetary quantities must be handled as integer minor units (e.g. cents). Log immutable audit trails."
                ),
                priority=110,
            )
        )
        self.register_rule(
            TriggeredRule(
                rule_id="rule_auth_security",
                domain=TriggerDomainKind.AUTH_SECURITY,
                path_patterns=["*auth*", "*token*", "*secret*", "*credential*", "*security*"],
                keyword_patterns=["auth", "login", "jwt", "password", "token", "credential", "permission", "rbac"],
                content=(
                    "AUTH & SECURITY DISCIPLINE: Zero secret exposure; never log auth headers or tokens. "
                    "Enforce least-privilege RBAC. Validate all redirect destinations against strict domain allowlists."
                ),
                priority=120,
            )
        )
        self.register_rule(
            TriggeredRule(
                rule_id="rule_frontend_ui",
                domain=TriggerDomainKind.FRONTEND_UI,
                path_patterns=["*component*", "*page*", "*view*", "*.tsx", "*.vue", "*.css"],
                keyword_patterns=["ui", "component", "render", "dom", "layout", "css", "style", "frontend"],
                content=(
                    "FRONTEND & A11Y DISCIPLINE: Ensure semantic HTML and proper ARIA role attributes. "
                    "Avoid cascading layout shifts (CLS). Keep components functional, typed, and decoupled from global stores."
                ),
                priority=80,
            )
        )
        self.register_rule(
            TriggeredRule(
                rule_id="rule_system_perf",
                domain=TriggerDomainKind.SYSTEM_PERF,
                path_patterns=["*cache*", "*worker*", "*concurrency*", "*pool*", "*queue*"],
                keyword_patterns=["performance", "latency", "throughput", "memory", "concurrency", "cache", "async"],
                content=(
                    "PERFORMANCE DISCIPLINE: Never perform blocking I/O within asynchronous event loops. "
                    "Set explicit timeouts on network sockets. Enforce bounded LRU or TTL policies on in-memory caches."
                ),
                priority=85,
            )
        )

    def register_rule(self, rule: TriggeredRule) -> None:
        """Register a new triggered domain rule."""
        self._rules.append(rule)

    def route_rules(
        self,
        target_paths: Sequence[str] = (),
        intent_text: str = "",
    ) -> Sequence[TriggeredRule]:
        """Match and select relevant domain rules based on file paths and intent keywords."""
        matched: Dict[str, TriggeredRule] = {}
        intent_lower = intent_text.lower()

        for rule in self._rules:
            # 1. Path match check
            path_hit = False
            for p in target_paths:
                p_normalized = p.replace("\\", "/").lower()
                for pattern in rule.path_patterns:
                    if fnmatch.fnmatch(p_normalized, pattern.lower()) or pattern.lower() in p_normalized:
                        path_hit = True
                        break
                if path_hit:
                    break

            # 2. Intent keyword match check
            keyword_hit = False
            if intent_lower:
                for kw in rule.keyword_patterns:
                    if kw.lower() in intent_lower:
                        keyword_hit = True
                        break

            if path_hit or keyword_hit:
                matched[rule.rule_id] = rule

        # Sort by priority descending
        sorted_rules = sorted(matched.values(), key=lambda r: r.priority, reverse=True)
        return sorted_rules[: self._config.max_triggered_rules]

    def total_registered_rules(self) -> int:
        """Return total count of registered domain rules."""
        return len(self._rules)
