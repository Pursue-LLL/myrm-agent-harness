"""Copy contract of the generic `unknown` diagnostic.

The fallback diagnosis reaches end users verbatim (chat error card), so its text must
- carry the provider's message in every shipped locale (a catalog placeholder that the engine never fills
  silently renders an empty tail), and
- never point users at library internals they cannot act on.
"""

import pytest

from myrm_agent_harness.agent.errors.diagnostics import LLMErrorDiagnostic

_LOCALES = ("en", "zh-CN", "ja", "ko", "de")
_INTERNAL_TERMS = ("litellm", "llmconfig", "debug", "base_url", "api_key", "调试", "デバッグ", "디버그")
_RAW_ERROR = "provider rejected the request (code 4711)"


@pytest.mark.parametrize("locale", _LOCALES)
def test_unknown_message_carries_the_provider_text(locale: str) -> None:
    result = LLMErrorDiagnostic.diagnose(RuntimeError(_RAW_ERROR), locale=locale)

    assert result.error_type == "unknown"
    assert result.locale == locale
    assert _RAW_ERROR in result.user_message
    assert not result.user_message.rstrip().endswith((":", "："))


@pytest.mark.parametrize("locale", _LOCALES)
def test_unknown_steps_do_not_expose_library_internals(locale: str) -> None:
    result = LLMErrorDiagnostic.diagnose(RuntimeError(_RAW_ERROR), locale=locale)

    assert result.resolution_steps
    for step in result.resolution_steps:
        assert not any(term in step.lower() for term in _INTERNAL_TERMS), step
