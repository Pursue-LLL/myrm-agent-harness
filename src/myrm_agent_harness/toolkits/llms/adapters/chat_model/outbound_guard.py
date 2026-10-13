"""Outbound message guard: the single hook every ChatLiteLLM call passes before its messages leave the process.

A host registers one guard; ChatLiteLLM calls it with the final wire messages of each request, so a policy
(PII masking, DLP) covers every caller of the model without each call site having to remember it. The guard
rewrites the messages in place. A guard that raises stops the call: text it could not vet is never sent.

[INPUT]
- none (pure registry)

[OUTPUT]
- OutboundMessageGuard: the guard signature, in-place over the wire messages of one request
- set_outbound_message_guard: register the guard, or None to remove it
- apply_outbound_message_guard: run the registered guard over a request's wire messages

[POS]
Extension point between the LLM adapter and the policy layers above it; the adapter knows nothing of the policy.
"""

from __future__ import annotations

from collections.abc import Callable

OutboundMessageGuard = Callable[[list[dict[str, object]]], None]

_guard: OutboundMessageGuard | None = None


def set_outbound_message_guard(guard: OutboundMessageGuard | None) -> None:
    """Register *guard* for every ChatLiteLLM request in this process, or remove it with None."""
    global _guard
    _guard = guard


def apply_outbound_message_guard(message_dicts: list[dict[str, object]]) -> None:
    """Run the registered guard over *message_dicts*; a no-op while none is registered."""
    if _guard is not None:
        _guard(message_dicts)
