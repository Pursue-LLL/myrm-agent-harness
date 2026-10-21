"""Model-specific outbound kwarg sanitization.

[INPUT]
- (none — pure model-name driven helpers)

[OUTPUT]
- get_unsupported_models(): models that reject response_format
- should_skip_response_format(): whether a model must drop response_format
- clean_model_kwargs(): strip internal keys and apply per-model parameter fixes

[POS]
Model-parameter compatibility layer. Distinct from litellm_utils.py (which owns
tool-argument JSON recovery): this module keeps provider quirks — internal marker
keys, qwen response_format, Kimi temperature floor — out of the JSON recovery path.
"""

from __future__ import annotations

_KIMI_TOOL_CALL_MIN_TEMP = 1.0
_KIMI_PREFIXES = ("moonshot/", "kimi/")


def get_unsupported_models() -> list[str]:
    return ["qwen-plus"]


def should_skip_response_format(model: str) -> bool:
    unsupported_models = get_unsupported_models()
    return any(unsupported in (model or "") for unsupported in unsupported_models)


def _needs_temperature_floor(model: str) -> bool:
    """Kimi K2.5 requires temperature >= 1.0 when using function calling."""
    lower = (model or "").lower()
    return any(lower.startswith(p) for p in _KIMI_PREFIXES)


def clean_model_kwargs(
    kwargs: dict[str, object], model: str, additional_remove_keys: list[str] | None = None
) -> dict[str, object]:
    if additional_remove_keys is None:
        additional_remove_keys = []
    remove_keys = ["_in_fallback", "_json_mode_fallback", *additional_remove_keys]
    if should_skip_response_format(model):
        remove_keys.append("response_format")
    cleaned = {k: v for k, v in kwargs.items() if k not in remove_keys}
    if "model_kwargs" in cleaned and isinstance(cleaned["model_kwargs"], dict):
        cleaned["model_kwargs"] = {k: v for k, v in cleaned["model_kwargs"].items() if k not in remove_keys}

    if _needs_temperature_floor(model):
        temp = cleaned.get("temperature")
        if isinstance(temp, (int, float)) and temp < _KIMI_TOOL_CALL_MIN_TEMP:
            cleaned["temperature"] = _KIMI_TOOL_CALL_MIN_TEMP

    return cleaned
