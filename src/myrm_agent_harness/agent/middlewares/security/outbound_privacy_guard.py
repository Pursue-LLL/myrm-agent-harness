"""Outbound privacy guard: the privacy policy applied to every ChatLiteLLM call the guardrail middleware does not cover.

The guardrail middleware screens the messages of an agent loop. Everything else that calls a chat model with conversation
text - memory extraction, summaries, titles, sub-agents without the middleware, background jobs - reaches the provider
through ChatLiteLLM. This guard sits on that one path and applies the same policy to the wire messages, so a call site
needs no privacy code of its own. A call that goes straight to litellm or a provider SDK, and a non-chat call
(embeddings, speech, image, video), does not pass through it.

The policy comes from the agent run when one is active, else from the process-wide policy a host publishes for work
that has no run (an HTTP request, a scheduled job). A loop whose middleware already enforced an enabled policy marks
its model calls, and the guard leaves those alone. The rewrites are the policy's own actions, so text the middleware
already processed passes through byte for byte and prompt caches stay valid.

[INPUT]
- agent.middlewares._session_context::get_privacy_policy (POS: Middleware session context — shared ContextVars for the middleware chain.)
- agent.middlewares.security.pii_actions::apply_privacy_policy (POS: PII action engine shared by the guardrail's input and output layers and by the tool-result PII guard.)
- agent.middlewares.security.text_blocks::map_text_blocks (POS: Content-shape adapter between a message and the security layers that rewrite its text.)
- agent.security.types::PrivacyPolicy (POS: Foundation layer of the security type hierarchy. All other security modules import from here; this module imports from none of them.)
- toolkits.llms.adapters.chat_model.outbound_guard::set_outbound_message_guard (POS: Extension point between the LLM adapter and the policy layers above it; the adapter knows nothing of the policy.)

[OUTPUT]
- set_process_privacy_policy: publish (or clear) the policy for model calls outside any agent run; enabling it installs the guard
- resolve_privacy_policy: the policy in force for the current call
- install_outbound_privacy_guard: register the guard on ChatLiteLLM (idempotent)
- guard_outbound_messages: mask the wire messages of one request in place
- sanitize_outbound_text: the same masking for one text, for callers that hand text to a model through a path of their own
- privacy_enforced_by_loop / is_privacy_enforced_by_loop: mark the model calls of a loop whose middleware enforces an enabled policy

[POS]
Wire-level half of the privacy layer: the guardrail middleware covers the agent loop, this guard covers every other ChatLiteLLM call.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from myrm_agent_harness.agent.middlewares._session_context import get_privacy_policy
from myrm_agent_harness.agent.middlewares.security.pii_actions import apply_privacy_policy
from myrm_agent_harness.agent.middlewares.security.text_blocks import map_text_blocks
from myrm_agent_harness.agent.security.types import PrivacyPolicy
from myrm_agent_harness.toolkits.llms.adapters.chat_model.outbound_guard import set_outbound_message_guard

_SOURCE = "outbound_llm"
# Instructions are the operator's own text, not conversation content.
_UNGUARDED_ROLES = frozenset({"system", "developer"})

_process_policy: PrivacyPolicy | None = None
_loop_enforced: ContextVar[bool] = ContextVar("privacy_enforced_by_loop", default=False)


def set_process_privacy_policy(policy: PrivacyPolicy | None) -> None:
    """Publish *policy* for model calls that run outside any agent run, or clear it with None."""
    global _process_policy
    _process_policy = policy
    if policy is not None and policy.enabled:
        install_outbound_privacy_guard()


def resolve_privacy_policy() -> PrivacyPolicy:
    """The enabled policy of the current agent run, else the process policy, else a disabled one."""
    run_policy = get_privacy_policy()
    if run_policy.enabled:
        return run_policy
    return _process_policy if _process_policy is not None else run_policy


def install_outbound_privacy_guard() -> None:
    """Register the guard on every ChatLiteLLM request in this process. Safe to call repeatedly."""
    set_outbound_message_guard(guard_outbound_messages)


@contextmanager
def privacy_enforced_by_loop(enforced: bool) -> Iterator[None]:
    """Mark the model calls made inside the block as already covered by the loop's own guardrail."""
    token = _loop_enforced.set(enforced)
    try:
        yield
    finally:
        _loop_enforced.reset(token)


def is_privacy_enforced_by_loop() -> bool:
    return _loop_enforced.get()


def guard_outbound_messages(message_dicts: list[dict[str, object]]) -> None:
    """Apply the policy in force to the text of every conversation message of one request, in place."""
    if _loop_enforced.get():
        return
    policy = resolve_privacy_policy()
    if not policy.enabled:
        return

    def mask(text: str) -> str:
        return apply_privacy_policy(text, policy, _SOURCE, audit=False)

    for message in message_dicts:
        if message.get("role") in _UNGUARDED_ROLES:
            continue
        content = message.get("content")
        if isinstance(content, (str, list)):
            message["content"] = map_text_blocks(content, mask)


def sanitize_outbound_text(text: str) -> str:
    """Apply the policy in force to one text; unchanged while no policy is enabled."""
    policy = resolve_privacy_policy()
    return apply_privacy_policy(text, policy, _SOURCE, audit=False) if policy.enabled else text
