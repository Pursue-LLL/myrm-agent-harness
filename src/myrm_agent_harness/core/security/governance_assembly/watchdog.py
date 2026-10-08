"""Runtime Zero-Bypass Watchdog and Tool Governance Wrapper.

Ensures that no internal cycle, subagent DAG, or programmatic tool caller can execute
a raw/naked callable without passing through the required governance middleware chain.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable, Sequence
from typing import Final

from myrm_agent_harness.core.security.governance_assembly.types import (
    GovernanceWrapperSignature,
    IngressSource,
    UngovernedToolExecutionError,
)

GOVERNANCE_SIGNATURE_ATTR: Final[str] = "__governance_signature__"

DEFAULT_MANDATORY_MIDDLEWARES: Final[tuple[str, ...]] = (
    "EStopCheck",
    "LoopGuard",
    "ToolInterceptorMiddleware",
    "TripartiteLedgerGate",
)


def is_governance_wrapped(tool_callable: object) -> bool:
    """Check if a callable or tool object possesses a valid governance wrapper signature."""
    sig = getattr(tool_callable, GOVERNANCE_SIGNATURE_ATTR, None)
    return isinstance(sig, GovernanceWrapperSignature) and sig.is_sealed


def get_governance_signature(tool_callable: object) -> GovernanceWrapperSignature | None:
    """Retrieve the governance wrapper signature if present."""
    sig = getattr(tool_callable, GOVERNANCE_SIGNATURE_ATTR, None)
    if isinstance(sig, GovernanceWrapperSignature):
        return sig
    return None


def wrap_with_governance(
    tool_callable: Callable[..., str],
    tool_name: str,
    ingress_source: IngressSource = IngressSource.INTERACTIVE_CHAT,
    middlewares: Sequence[str] | None = None,
) -> Callable[..., str]:
    """Wrap a callable in an immutable governance proxy with signature verification."""
    applied = tuple(middlewares) if middlewares is not None else DEFAULT_MANDATORY_MIDDLEWARES
    wrapper_id = f"gov-wrap-{uuid.uuid4().hex[:12]}"

    sig = GovernanceWrapperSignature(
        wrapper_id=wrapper_id,
        tool_name=tool_name,
        ingress_source=ingress_source,
        applied_middlewares=applied,
        is_sealed=True,
    )

    @functools.wraps(tool_callable)
    def governed_wrapper(*args: object, **kwargs: object) -> str:
        # Runtime re-assertion: ensure signature hasn't been stripped
        if not is_governance_wrapped(governed_wrapper):
            raise UngovernedToolExecutionError(
                f"Governance signature revoked or stripped on tool '{tool_name}'"
            )
        return tool_callable(*args, **kwargs)

    setattr(governed_wrapper, GOVERNANCE_SIGNATURE_ATTR, sig)
    return governed_wrapper


class RuntimeZeroBypassWatchdog:
    """Watchdog asserting governance wrapping across all execution pathways."""

    def __init__(self, mandatory_middlewares: Sequence[str] | None = None) -> None:
        self._mandatory_middlewares = (
            tuple(mandatory_middlewares)
            if mandatory_middlewares is not None
            else DEFAULT_MANDATORY_MIDDLEWARES
        )

    def verify_tool(self, tool_callable: object, tool_name: str) -> GovernanceWrapperSignature:
        """Verify that a single tool callable is wrapped with all mandatory governance guards."""
        sig = get_governance_signature(tool_callable)
        if sig is None or not sig.is_sealed:
            raise UngovernedToolExecutionError(
                f"Naked tool execution detected for '{tool_name}': tool is not wrapped "
                "by required governance middlewares"
            )

        missing = [m for m in self._mandatory_middlewares if m not in sig.applied_middlewares]
        if missing:
            raise UngovernedToolExecutionError(
                f"Tool '{tool_name}' governance chain is incomplete: missing {missing}"
            )

        return sig

    def verify_tool_registry(self, tools: Sequence[tuple[str, object]]) -> None:
        """Verify a collection of registered tools before binding to Agent runtime."""
        for name, tool_obj in tools:
            self.verify_tool(tool_obj, name)

    def execute_governed_tool(
        self,
        tool_callable: Callable[..., str],
        tool_name: str,
        *args: object,
        **kwargs: object,
    ) -> str:
        """Execute a tool while strictly enforcing zero-bypass governance validation."""
        self.verify_tool(tool_callable, tool_name)
        return tool_callable(*args, **kwargs)
