"""Per-call ``allowed_openai_params`` injection for ChatLiteLLM.

[INPUT]
- chat_model.exceptions::_FRAMEWORK_REQUIRED_OPENAI_PARAMS (POS: params LiteLLM must never drop)
- wire.native_anthropic::is_native_anthropic_wire (POS: first-party Anthropic Messages API detection)

[OUTPUT]
- inject_allowed_params(): white-list a call's own parameters against LiteLLM's provider filter

[POS]
Per-call parameter-protection step of ChatLiteLLM, bound as ``ChatLiteLLM._inject_allowed_params``.
First-party Anthropic Messages API calls are skipped because that API rejects the raw OpenAI-shaped copies.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.adapters.chat_model.exceptions import _FRAMEWORK_REQUIRED_OPENAI_PARAMS
from myrm_agent_harness.toolkits.llms.adapters.wire.native_anthropic import is_native_anthropic_wire


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def inject_allowed_params(params: dict[str, object]) -> None:
    """Ensure all explicitly-supplied parameters bypass LiteLLM's provider whitelist.

    LiteLLM silently drops parameters not declared in a provider's
    ``supported_params`` when ``litellm.drop_params=True``.  Some providers
    (e.g. ``xiaomi_mimo``) have incomplete capability declarations, causing
    critical params like ``tools`` / ``tool_choice`` — and any user-supplied
    model_kwargs — to be discarded.

    This injects ``allowed_openai_params`` into *params* so that every key
    we explicitly passed is white-listed for the current call, while the
    global ``drop_params`` safety-net remains active for truly unknown params.

    ``tool_choice.type=allowed_tools`` is excluded from forced whitelisting so
    unsupported gateways can drop it instead of returning HTTP 400.

    Calls to the first-party Anthropic Messages API get no whitelist: LiteLLM's own
    translation already maps everything the framework sends there (tools, tool_choice,
    thinking, stop sequences, ...), and the raw copies the whitelist adds are rejected.
    """
    if is_native_anthropic_wire(
        _text(params.get("model")) or "",
        _text(params.get("api_base")),
        _text(params.get("custom_llm_provider")),
    ):
        return

    allowed = set(params.keys())
    allowed |= _FRAMEWORK_REQUIRED_OPENAI_PARAMS
    tool_choice = params.get("tool_choice")
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "allowed_tools":
        allowed.discard("tool_choice")
    params["allowed_openai_params"] = sorted(allowed)
