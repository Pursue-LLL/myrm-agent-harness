"""The domain allow/block lists of one browser context, with the single rule that applies them.

[INPUT]
- patchright.async_api::BrowserContext (POS: browser context the lists are bound to)

[OUTPUT]
- DomainListPolicy: verdict for one hostname against a context's block and allow lists
- bind_domain_lists: record a context's policy when the request filter is installed
- domain_lists_for: the policy bound to a context, if any

[POS]
Shared state between the context-level request filter (judges every request it is handed) and the
navigation guard (judges the redirect hops the filter is never handed). Both ask the same policy
about the same context, so a hostname gets the same verdict whichever way it was reached. Keyed by
the ``BrowserContext`` object like ``utils.private_origins``: pooled contexts are created per
policy, so the lists never leak between sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext

    from myrm_agent_harness.toolkits.browser.domain_filter import DomainAllowlist, DomainBlocklist

DomainListViolation = Literal["blocklist", "allowlist"]


@dataclass(frozen=True, slots=True)
class DomainListPolicy:
    """Blocklist first, then allowlist; an empty list imposes nothing."""

    allowlist: DomainAllowlist
    blocklist: DomainBlocklist | None = None

    @property
    def is_empty(self) -> bool:
        return self.allowlist.is_empty and (self.blocklist is None or self.blocklist.is_empty)

    def violation(self, hostname: str) -> DomainListViolation | None:
        """Name the list that forbids ``hostname``, or None when it may be reached."""
        if self.blocklist is not None and not self.blocklist.is_empty and self.blocklist.is_blocked(hostname):
            return "blocklist"
        if not self.allowlist.is_empty and not self.allowlist.is_allowed(hostname):
            return "allowlist"
        return None


_POLICY_BY_CONTEXT: WeakKeyDictionary[BrowserContext, DomainListPolicy] = WeakKeyDictionary()


def bind_domain_lists(context: BrowserContext, policy: DomainListPolicy) -> None:
    _POLICY_BY_CONTEXT[context] = policy


def domain_lists_for(context: BrowserContext) -> DomainListPolicy | None:
    return _POLICY_BY_CONTEXT.get(context)
