"""Source-engine style declarative Convar configuration system and scoped inheritance suite.

[OUTPUT]
- ConvarType: Primitive types supported by Convars.
- ConvarFlags: Bitflags governing persistence, replication, and mutability.
- ConvarDefinition: Immutable schema prototype for declared Convars.
- ConvarSnapshot: Evaluated state snapshot for a single variable in a scope.
- ConvarRegistry: Central repository managing definitions and type conversions.
- ScopedConvarContext: Hierarchical execution scope holding local overrides and dirty state.

[INPUT]
- __future__

[OUTPUT]
- (模块级副作用与注册)

[POS]
Source-engine style declarative Convar configuration system and scoped inheritance suite.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.convar.convar_registry import ConvarRegistry
from myrm_agent_harness.runtime.convar.convar_types import (
    ConvarDefinition,
    ConvarFlags,
    ConvarSnapshot,
    ConvarType,
)
from myrm_agent_harness.runtime.convar.scoped_convar_context import (
    ConvarChangeListener,
    ScopedConvarContext,
)

__all__ = [
    "ConvarChangeListener",
    "ConvarDefinition",
    "ConvarFlags",
    "ConvarRegistry",
    "ConvarSnapshot",
    "ConvarType",
    "ScopedConvarContext",
]
