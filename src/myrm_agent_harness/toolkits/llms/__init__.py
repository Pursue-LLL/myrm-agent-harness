from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core.credential_pool import CredentialPoolStrategy
    from .core.llm import ChatLiteLLM, create_litellm_model
    from .core.manager import LLMManager, llm_manager
    from .errors.classifier import ErrorKind, classify_error, extract_retry_after, is_context_overflow
    from .errors.resilient import resilient_llm_call

__all__ = [
    "ChatLiteLLM",
    "CredentialPoolStrategy",
    "ErrorKind",
    "LLMManager",
    "classify_error",
    "create_litellm_model",
    "extract_retry_after",
    "is_context_overflow",
    "llm_manager",
    "resilient_llm_call",
]

_LAZY_IMPORTS = {
    "ChatLiteLLM": ("myrm_agent_harness.toolkits.llms.core.llm", "ChatLiteLLM"),
    "CredentialPoolStrategy": ("myrm_agent_harness.toolkits.llms.core.credential_pool", "CredentialPoolStrategy"),
    "create_litellm_model": ("myrm_agent_harness.toolkits.llms.core.llm", "create_litellm_model"),
    "LLMManager": ("myrm_agent_harness.toolkits.llms.core.manager", "LLMManager"),
    "llm_manager": ("myrm_agent_harness.toolkits.llms.core.manager", "llm_manager"),
    "ErrorKind": ("myrm_agent_harness.toolkits.llms.errors.classifier", "ErrorKind"),
    "classify_error": ("myrm_agent_harness.toolkits.llms.errors.classifier", "classify_error"),
    "extract_retry_after": ("myrm_agent_harness.toolkits.llms.errors.classifier", "extract_retry_after"),
    "is_context_overflow": ("myrm_agent_harness.toolkits.llms.errors.classifier", "is_context_overflow"),
    "resilient_llm_call": ("myrm_agent_harness.toolkits.llms.errors.resilient", "resilient_llm_call"),
}

if __debug__:
    _lazy_set = set(_LAZY_IMPORTS.keys())
    _all_set = set(__all__)
    _extra = _lazy_set - _all_set
    if _extra:
        raise RuntimeError(f"llms: _LAZY_IMPORTS has symbols not in __all__: {_extra}")


def __getattr__(name: str):
    """Lazy load llms components on first access."""
    if name in _LAZY_IMPORTS:
        from importlib import import_module

        module_path, attr_name = _LAZY_IMPORTS[name]
        module = import_module(module_path)

        if attr_name == "llm_manager":
            from myrm_agent_harness.toolkits.llms import config  # noqa: F401  # side-effect: ensure config loaded

        value = getattr(module, attr_name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
