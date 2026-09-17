"""Core security detection — PII classification, leak detection, prompt injection guard, intent router.

[INPUT]
- core.security.detection.content_boundary::extract_wrapped_payload, sanitize,
  strip_invisible_unicode, wrap_tool_output, wrap_untrusted
  (POS: 不可信内容边界包裹与净化层)
- core.security.detection.instruction_shape::InstructionShapeLabel,
  detect_instruction_shapes (POS: 指令形状识别层)
- core.security.detection.intent_router::DangerousIntent, IntentSafetyResult,
  scan_dangerous_intent (POS: 危险意图路由层)
- core.security.detection.leak_detector::redact_leaks, scan_for_leaks
  (POS: 凭据与敏感信息泄漏检测层)
- core.security.detection.pii_classifier::PIIClassification, classify_content
  (POS: 个人身份信息分类层)
- core.security.detection.prompt_guard::GuardResult, log_guard_result, scan_input
  (POS: 提示注入防护层)

[OUTPUT]
- Content boundary, instruction-shape, intent-routing, leak-detection, PII-classification
  and prompt-injection guard primitives

[POS]
Public surface of the core security detection package. Aggregates the deterministic guardrails
that inspect untrusted text before it reaches the model or the user.
"""

from .content_boundary import (
    extract_wrapped_payload,
    sanitize,
    strip_invisible_unicode,
    wrap_tool_output,
    wrap_untrusted,
)
from .instruction_shape import (
    InstructionShapeLabel,
    detect_instruction_shapes,
)
from .intent_router import (
    DangerousIntent,
    IntentSafetyResult,
    scan_dangerous_intent,
)
from .leak_detector import (
    redact_leaks,
    scan_for_leaks,
)
from .pii_classifier import (
    PIIClassification,
    classify_content,
)
from .prompt_guard import (
    GuardResult,
    log_guard_result,
    scan_input,
)

__all__ = [
    "DangerousIntent",
    "GuardResult",
    "InstructionShapeLabel",
    "IntentSafetyResult",
    "PIIClassification",
    "classify_content",
    "detect_instruction_shapes",
    "extract_wrapped_payload",
    "log_guard_result",
    "redact_leaks",
    "sanitize",
    "scan_dangerous_intent",
    "scan_for_leaks",
    "scan_input",
    "strip_invisible_unicode",
    "wrap_tool_output",
    "wrap_untrusted",
]
