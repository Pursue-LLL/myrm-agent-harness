"""Semantic DOM risk classification for browser interactions.

Layers browser-specific action preconditions (mutating actions, activation
keys, JS evaluate patterns) on top of the shared cross-channel destructive
element lexicon from ``core.security.detection.semantic_risk``, so a browser
element interaction and a desktop AX element interaction are gated by one
identical high-risk vocabulary.

[INPUT]
- core.security.detection.semantic_risk::SemanticRiskLevel, RiskVerdict,
  classify_element_risk (POS: 跨通道破坏性控件语义词典 SSOT)
- snapshot::RefInfo (POS: element ref metadata with role/name)

[OUTPUT]
- classify_interaction_risk: classify (action, RefInfo) → risk level + reason
- classify_js_eval_risk: classify browser_manage evaluate expressions

[POS]
Pure function module — no side effects, no I/O. Consumed by semantic_dom_hitl
(session.interact and evaluate HITL gates) before element interaction or JS eval.
"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.detection.semantic_risk import (
    RiskVerdict,
    SemanticRiskLevel,
    classify_element_risk,
)
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo

__all__ = [
    "RiskVerdict",
    "SemanticRiskLevel",
    "classify_interaction_risk",
    "classify_js_eval_risk",
]

_MUTATING_ACTIONS = frozenset({"click", "dblclick", "check", "uncheck"})
_ACTIVATION_KEYS = frozenset({"enter", "return", "space", "numpadenter", "\n", "\r\n"})

_JS_MUTATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\.click\s*\("), "DOM click via JS"),
    (re.compile(r"\.dblclick\s*\("), "DOM double-click via JS"),
    (re.compile(r"\.dispatchEvent\s*\("), "Synthetic DOM event"),
    (re.compile(r"\.submit\s*\("), "Form submission via JS"),
    (re.compile(r"\bsubmit\s*\("), "Form submission via JS"),
    (re.compile(r"\.remove\s*\("), "DOM node removal"),
    (re.compile(r"removeChild\s*\("), "DOM node removal"),
    (re.compile(r"innerHTML\s*="), "DOM content overwrite"),
    (re.compile(r"outerHTML\s*="), "DOM content overwrite"),
    (re.compile(r"document\.write\s*\("), "Document write"),
    (re.compile(r"\beval\s*\("), "Dynamic code execution"),
    (re.compile(r"location\.(?:href|assign|replace)\s*="), "Navigation redirect"),
    (re.compile(r"location\.(?:assign|replace)\s*\("), "Navigation redirect"),
    (re.compile(r"fetch\s*\([^)]*method\s*:\s*['\"]post", re.IGNORECASE), "Network POST"),
    (re.compile(r"XMLHttpRequest"), "Legacy XHR mutation"),
    (re.compile(r"删除"), "destructive"),
    (re.compile(r"支付|付款|购买|下单"), "financial"),
    (re.compile(r"发布|广播"), "publish"),
)


def classify_js_eval_risk(expression: str) -> RiskVerdict:
    """Classify risk for browser_manage / session JS evaluate expressions."""
    stripped = expression.strip()
    if not stripped:
        return RiskVerdict(SemanticRiskLevel.SAFE, "")

    lowered = stripped.lower()
    for pattern, category in _JS_MUTATION_PATTERNS:
        if pattern.search(stripped) or pattern.search(lowered):
            preview = stripped[:120] + ("…" if len(stripped) > 120 else "")
            return RiskVerdict(
                SemanticRiskLevel.HIGH,
                f"{category}: JS evaluate `{preview}`",
            )

    return RiskVerdict(SemanticRiskLevel.SAFE, "")


def classify_interaction_risk(
    action: str,
    ref_info: RefInfo,
    text: str = "",
) -> RiskVerdict:
    """Classify the risk of an element interaction based on semantic content.

    Mutating actions (click, dblclick, or press with activation keys like Enter/Space)
    on elements whose name or role signals a destructive/financial/admin operation
    are classified as HIGH.
    Read-only actions (hover, focus, scroll, scroll_to_bottom) and non-activation keys
    (Tab, Escape, arrows) are always SAFE.
    browser_extract (all modes: text, screenshot, media, diff) is inherently read-only.

    Args:
        action: The interaction action (click, fill, hover, press, ...).
        ref_info: ARIA metadata of the target element.
        text: Optional key name or input text associated with the action (e.g. for press).

    Returns:
        RiskVerdict with level and human-readable reason.
    """
    is_mutating = action in _MUTATING_ACTIONS
    is_key_activation = False

    if not is_mutating and action == "press":
        if isinstance(text, str):
            raw_key = text.lower()
            clean_key = raw_key.strip()
            if (
                clean_key in _ACTIVATION_KEYS
                or raw_key in _ACTIVATION_KEYS
                or any(clean_key.endswith(k) for k in ("+enter", "+return", "+space", "+numpadenter"))
            ):
                is_mutating = True
                is_key_activation = True
    elif not is_mutating and action == "type" and isinstance(text, str) and ("\n" in text or "\r" in text):
        is_mutating = True
        is_key_activation = True

    if not is_mutating:
        return RiskVerdict(SemanticRiskLevel.SAFE, "")

    key_suffix = f" (key activation [{text}])" if is_key_activation else ""

    verdict = classify_element_risk(ref_info.role, ref_info.name)
    if verdict.level is not SemanticRiskLevel.HIGH:
        return RiskVerdict(SemanticRiskLevel.SAFE, "")

    return RiskVerdict(
        SemanticRiskLevel.HIGH,
        f"{verdict.reason}{key_suffix}",
    )
