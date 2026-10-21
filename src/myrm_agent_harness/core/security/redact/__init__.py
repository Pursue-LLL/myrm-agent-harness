"""Public facade for the secret redaction domain.

Aggregates the redaction engine (``engine.py``) and shared masking helpers
(``patterns.py``) behind ``core.security.redact``, exposing a stable public
import surface: ``redact_sensitive_text``, ``redact_for_llm``,
``redact_for_display``, ``RedactingFormatter``, ``set_redact_enabled``, plus the
internal symbols re-exported by the ``agent.security.redact`` facade.

[INPUT]
- (none — aggregation facade)

[OUTPUT]
- redact_sensitive_text / redact_for_llm / redact_for_display / escape_invisible_unicode / RedactingFormatter / set_redact_enabled — public API
- _mask_token / _redact_pem_block / _redact_value_recursive / _replace_pattern_bounded — internal helpers
"""

from .engine import (
    RedactingFormatter,
    _redact_pem_block,
    _redact_value_recursive,
    _replace_pattern_bounded,
    escape_invisible_unicode,
    redact_for_display,
    redact_for_llm,
    redact_sensitive_text,
    set_redact_enabled,
)
from .patterns import _mask_token

__all__ = [
    "RedactingFormatter",
    "_mask_token",
    "_redact_pem_block",
    "_redact_value_recursive",
    "_replace_pattern_bounded",
    "escape_invisible_unicode",
    "redact_for_display",
    "redact_for_llm",
    "redact_sensitive_text",
    "set_redact_enabled",
]
