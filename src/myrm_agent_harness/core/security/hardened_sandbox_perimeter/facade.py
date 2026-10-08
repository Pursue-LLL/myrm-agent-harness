"""
[POS] src/myrm_agent_harness/core/security/hardened_sandbox_perimeter/facade.py
[INPUT] collections.abc, threading, typing, .types, .runtime_spec_validator, .ssrf_egress_shield, .credential_broker, .resource_process_guard
[OUTPUT] HardenedSandboxPerimeterSuite

Unified facade for Scale-Ready Hardened Agent Sandbox & Safety Perimeter Suite.
Coordinates container runtime hardening verification, SSRF and egress firewall defenses,
out-of-band credential brokering, and OS-level cgroups v2 / fork-bomb process mitigation.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from .credential_broker import ZeroLeakCredentialBroker
from .resource_process_guard import ResourceProcessGuard
from .runtime_spec_validator import RuntimeSpecValidator
from .ssrf_egress_shield import SsrfEgressShield
from .types import (
    BrokerCredentialTicket,
    EgressEvaluationResult,
    EgressTarget,
    EgressVerdictEnum,
    HardenedSandboxSpec,
    ProcessUsageSnapshot,
    RuntimeSpecValidationResult,
    SandboxSafetyMetrics,
)


class HardenedSandboxPerimeterSuite:
    """Thread-safe defense-in-depth perimeter suite for hardened agent sandboxes."""

    def __init__(
        self,
        dns_resolver_fn: Callable[[str], list[str]] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self.spec_validator = RuntimeSpecValidator()
        self.egress_shield = SsrfEgressShield(resolver_fn=dns_resolver_fn)
        self.credential_broker = ZeroLeakCredentialBroker()
        self.process_guard = ResourceProcessGuard()
        self._metrics = SandboxSafetyMetrics()

    def validate_runtime_spec(
        self, spec: HardenedSandboxSpec
    ) -> RuntimeSpecValidationResult:
        """Validate sandbox runtime startup spec against security standards."""
        result = self.spec_validator.validate_spec(spec)
        with self._lock:
            self._metrics.total_spec_validations += 1
            if not result.is_valid:
                self._metrics.spec_validation_failures += 1
        return result

    def evaluate_egress(
        self,
        target: EgressTarget,
        allowlisted_domains: list[str] | None = None,
    ) -> EgressEvaluationResult:
        """Evaluate outbound connection request to intercept SSRF and unauthorized destinations."""
        result = self.egress_shield.evaluate_egress(target, allowlisted_domains)
        with self._lock:
            self._metrics.egress_requests_evaluated += 1
            if result.verdict in (
                EgressVerdictEnum.BLOCKED_PRIVATE_IP,
                EgressVerdictEnum.BLOCKED_CLOUD_METADATA,
            ):
                self._metrics.ssrf_blocks += 1
        return result

    def register_secret(self, secret_alias: str, secret_value: str) -> None:
        """Register host master secret to be brokered out-of-band."""
        self.credential_broker.register_secret(secret_alias, secret_value)

    def has_secret(self, secret_alias: str) -> bool:
        """Query whether master secret alias is available."""
        return self.credential_broker.has_secret(secret_alias)

    def mint_ephemeral_ticket(
        self,
        secret_alias: str,
        allowed_scopes: list[str],
        ttl_seconds: float = 300.0,
    ) -> BrokerCredentialTicket:
        """Issue temporary scoped ticket to sandbox without revealing raw secrets."""
        ticket = self.credential_broker.mint_ticket(secret_alias, allowed_scopes, ttl_seconds)
        with self._lock:
            self._metrics.credential_tickets_minted += 1
        return ticket

    def verify_ticket(
        self,
        ticket_id: str,
        required_scope: str | None = None,
    ) -> bool:
        """Verify ticket validity for tool execution."""
        return self.credential_broker.verify_ticket(ticket_id, required_scope)

    def revoke_ticket(self, ticket_id: str) -> bool:
        """Revoke active ticket ahead of expiry."""
        return self.credential_broker.revoke_ticket(ticket_id)

    def evaluate_process_usage(
        self,
        agent_id: str,
        snapshot: ProcessUsageSnapshot,
        pids_max: int = 128,
        memory_limit_mb: float = 512.0,
    ) -> tuple[bool, str]:
        """Assess process count and resource allocation to prevent fork-bombs and OOM."""
        is_safe, msg = self.process_guard.evaluate_snapshot(
            agent_id=agent_id,
            snapshot=snapshot,
            pids_max=pids_max,
            memory_limit_mb=memory_limit_mb,
        )
        if not is_safe:
            with self._lock:
                self._metrics.fork_bomb_mitigations += 1
        return is_safe, msg

    def reset_process_guard(self, agent_id: str) -> bool:
        """Clear circuit-breaker trip for an agent."""
        return self.process_guard.reset_agent(agent_id)

    def is_process_guard_tripped(self, agent_id: str) -> bool:
        """Check if an agent is currently circuit-broken."""
        return self.process_guard.is_agent_tripped(agent_id)

    def get_metrics(self) -> SandboxSafetyMetrics:
        """Retrieve telemetry snapshot of sandbox security metrics."""
        with self._lock:
            return SandboxSafetyMetrics(
                total_spec_validations=self._metrics.total_spec_validations,
                spec_validation_failures=self._metrics.spec_validation_failures,
                egress_requests_evaluated=self._metrics.egress_requests_evaluated,
                ssrf_blocks=self._metrics.ssrf_blocks,
                credential_tickets_minted=self._metrics.credential_tickets_minted,
                fork_bomb_mitigations=self._metrics.fork_bomb_mitigations,
            )
