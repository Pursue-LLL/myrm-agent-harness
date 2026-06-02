"""Security detection subsystem — content analysis and PII protection.

Public API:
- Content classification: classify_content, scan_for_leaks, scan_input
- PII handling: redact_pii, pseudonymize_text, PseudonymRestorer
- Content boundary: sanitize, wrap_untrusted, wrap_tool_output
- Tool validation: validate_tool_result, should_apply_validation

[POS]
Agent Security Detection module.
"""

from .content_boundary import sanitize, wrap_tool_output, wrap_untrusted
from .leak_detector import redact_leaks, scan_for_leaks
from .pii_classifier import PIIClassification, classify_content
from .pii_redactor import redact_pii
from .prompt_guard import GuardResult, scan_input
from .pseudonym_store import PseudonymStore, get_pseudonym_store
from .pseudonymizer import PIIItem, PseudonymRestorer, pseudonymize_text
from .tool_result_validator import ValidationResult, should_apply_validation, validate_tool_result

__all__ = [
    "GuardResult",
    "PIIClassification",
    "PIIItem",
    "PseudonymRestorer",
    "PseudonymStore",
    "ValidationResult",
    "classify_content",
    "get_pseudonym_store",
    "pseudonymize_text",
    "redact_leaks",
    "redact_pii",
    "sanitize",
    "scan_for_leaks",
    "scan_input",
    "should_apply_validation",
    "validate_tool_result",
    "wrap_tool_output",
    "wrap_untrusted",
]
