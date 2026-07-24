"""Combo routing data models — the single source of truth for LLM routing configuration.

A *Combo* is an ordered chain of LLM targets. When one target exhausts its
quota, hits a rate limit, or encounters an error, the ComboResolver
transparently slides to the next target in the chain.

[INPUT]

[OUTPUT]
- RoutingStrategy: enum of 7 supported routing strategies
- ComboTarget: single target in a Combo chain
- ComboConfig: full Combo configuration (targets + strategy + metadata)

[POS]
Framework-level Combo type definitions. Consumed by ``combo.resolver``,
``passthrough`` (Server), and ``Settings GUI`` (Frontend).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RoutingStrategy(StrEnum):
    """Supported routing strategies for target ordering within a Combo.

    PRIORITY       — Ordered failover: exhaust each target in declared order.
    COST_OPTIMIZED — Sort by ``priority`` field as cost proxy; assign lower
                     priority numbers to cheaper targets.
    ROUND_ROBIN    — Rotate targets evenly across requests.
    RANDOM         — Randomly pick from available targets (uniform distribution).
    LKGP           — "Last Known Good Provider" — sticky on the most recent
                     successful target until it fails.
    CONTEXT_RELAY  — Maintain prompt-cache affinity: prefer the target that
                     served the most recent turns of the current conversation.
    HEADROOM       — Prefer the target with the largest remaining quota headroom.
    """

    PRIORITY = "priority"
    COST_OPTIMIZED = "cost_optimized"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LKGP = "lkgp"
    CONTEXT_RELAY = "context_relay"
    HEADROOM = "headroom"


class ComboTarget(BaseModel):
    """A single target slot inside a Combo chain.

    Each target corresponds to a ``provider_id / model`` pair that the
    resolver can route requests to.

    Attributes:
        provider_id: Provider identifier matching the user's Settings
                     (e.g. ``"openai"``, ``"anthropic"``, ``"deepseek"``).
        model: Raw model name within the provider (e.g. ``"gpt-4o"``).
        priority: Explicit ordering weight — lower wins when strategy is
                  ``PRIORITY`` (default 0 = first).
        weight: Proportional weight for ``ROUND_ROBIN`` / ``RANDOM``
                (default 1 = equal share).
        max_requests_per_minute: Optional per-target RPM cap.  When reached
                                 the resolver treats it as a soft quota
                                 exhaustion and slides to the next target.
        enabled: Whether this target is active (disabled targets are skipped).
    """

    provider_id: str
    model: str
    priority: int = 0
    weight: int = Field(default=1, ge=1)
    max_requests_per_minute: int | None = None
    enabled: bool = True


class ComboConfig(BaseModel):
    """Full Combo routing configuration.

    ``targets`` is the ordered chain; ``strategy`` controls how the resolver
    picks the next target on each request.

    Attributes:
        name: Human-readable label for Settings GUI (e.g. "My Coding Combo").
        targets: Ordered list of targets — at least one must be present.
        strategy: Routing strategy (default ``PRIORITY``).
        max_retries: Max cross-target retries before propagating the error
                     (default 3 = try up to 3 different targets).
        retry_on_status: HTTP status codes that trigger a retry/failover
                         (default: 429, 500, 502, 503, 529).
    """

    name: str = ""
    targets: list[ComboTarget] = Field(default_factory=list, min_length=0)
    strategy: RoutingStrategy = RoutingStrategy.PRIORITY
    max_retries: int = Field(default=3, ge=1, le=10)
    retry_on_status: frozenset[int] = frozenset({429, 500, 502, 503, 529})

    @property
    def is_empty(self) -> bool:
        """True when no targets are configured (single-provider fallback)."""
        return len(self.targets) == 0

    @property
    def enabled_targets(self) -> list[ComboTarget]:
        """Targets filtered to only enabled entries."""
        return [t for t in self.targets if t.enabled]
