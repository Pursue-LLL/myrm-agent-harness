"""Per-context registry of private-network origins a local-mode session navigated to.

[INPUT]
- core.security.redirect_hop_guard::PrivateOriginGrants (POS: explicit private origin set)

[OUTPUT]
- private_origin_grants: get-or-create the grants bound to a browser context

[POS]
Shared state between the navigation guard (records an origin when the agent navigates there on
purpose) and the context-level request filter (lets documents from granted origins through).
Both resolve the same ``BrowserContext`` object, so no wiring through factories is needed and a
recycled context never inherits another session's grants by accident of object identity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from myrm_agent_harness.core.security.redirect_hop_guard import PrivateOriginGrants

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext

_GRANTS_BY_CONTEXT: WeakKeyDictionary[BrowserContext, PrivateOriginGrants] = WeakKeyDictionary()


def private_origin_grants(context: BrowserContext) -> PrivateOriginGrants:
    grants = _GRANTS_BY_CONTEXT.get(context)
    if grants is None:
        grants = _GRANTS_BY_CONTEXT[context] = PrivateOriginGrants()
    return grants
