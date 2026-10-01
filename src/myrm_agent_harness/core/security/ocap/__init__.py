"""Object-Capability (OCap) zero-trust delegation mesh primitives.

[INPUT]
- .types::CapabilityAction, ResourceScope, CapabilityHandle, AttenuationError, CapabilityDeniedError
- .token::sign_capability_handle, verify_capability_signature, get_ocap_secret
- .attenuation::attenuate_capability, validate_scope_subset
- .registry::CapabilityRegistry, get_default_capability_registry
- .context::get_current_capability, set_current_capability, reset_current_capability, capability_scope
- .guard::check_capability_access, enforce_capability_access

[OUTPUT]
- Unified public interface for Object-Capability security mesh

[POS]
Foundational zero-trust Object-Capability primitives for Myrm Agent Harness.
Eliminates ambient authority across subagent delegation and task topologies.
"""

from myrm_agent_harness.core.security.ocap.attenuation import (
    attenuate_capability,
    validate_scope_subset,
)
from myrm_agent_harness.core.security.ocap.context import (
    capability_scope,
    get_current_capability,
    reset_current_capability,
    set_current_capability,
)
from myrm_agent_harness.core.security.ocap.guard import (
    check_capability_access,
    enforce_capability_access,
)
from myrm_agent_harness.core.security.ocap.registry import (
    CapabilityRegistry,
    get_default_capability_registry,
)
from myrm_agent_harness.core.security.ocap.token import (
    get_ocap_secret,
    sign_capability_handle,
    verify_capability_signature,
)
from myrm_agent_harness.core.security.ocap.types import (
    AttenuationError,
    CapabilityAction,
    CapabilityDeniedError,
    CapabilityHandle,
    ResourceScope,
)

__all__ = [
    "AttenuationError",
    "CapabilityAction",
    "CapabilityDeniedError",
    "CapabilityHandle",
    "CapabilityRegistry",
    "ResourceScope",
    "attenuate_capability",
    "capability_scope",
    "check_capability_access",
    "enforce_capability_access",
    "get_current_capability",
    "get_default_capability_registry",
    "get_ocap_secret",
    "reset_current_capability",
    "set_current_capability",
    "sign_capability_handle",
    "validate_scope_subset",
    "verify_capability_signature",
]
