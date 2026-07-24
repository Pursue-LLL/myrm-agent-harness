"""Combo routing engine — unified LLM target selection and failover.

A *Combo* is an ordered chain of LLM provider/model targets.  The
``ComboResolver`` walks the chain using one of seven routing strategies,
transparently failing over when a target exhausts its quota or errors.

[INPUT]
- llms.core.credential_pool (POS: multi-key dispatch)

[OUTPUT]
- ComboConfig, ComboTarget, RoutingStrategy: data models
- ComboResolver, ResolvedTarget: stateful resolver
- StrategyContext, apply_strategy: strategy engine

[POS]
Combo routing engine — single source of truth for LLM model/provider
selection across Agent and Passthrough paths.
"""

from .combo_types import ComboConfig, ComboTarget, RoutingStrategy
from .resolver import ComboResolver, ResolvedTarget
from .strategies import StrategyContext, apply_strategy

__all__ = [
    "ComboConfig",
    "ComboResolver",
    "ComboTarget",
    "ResolvedTarget",
    "RoutingStrategy",
    "StrategyContext",
    "apply_strategy",
]
