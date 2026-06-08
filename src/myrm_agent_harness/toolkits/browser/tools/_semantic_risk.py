"""Semantic DOM risk classification for browser interactions.

Classifies browser element interactions as high-risk based on the semantic
content of the target element (role + name from ARIA snapshot). When a
destructive action targets a dangerous element, the tool interrupts execution
to request explicit user approval via LangGraph's HITL mechanism.

[INPUT]
- snapshot::RefInfo (POS: element ref metadata with role/name)

[OUTPUT]
- SemanticRiskLevel: risk classification enum
- classify_interaction_risk: classify (action, RefInfo) → risk level + reason

[POS]
Pure function module — no side effects, no I/O. Called by browser_interact_tool
before element interaction to gate destructive operations.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple

from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo


class SemanticRiskLevel(Enum):
    SAFE = "safe"
    HIGH = "high"


class RiskVerdict(NamedTuple):
    level: SemanticRiskLevel
    reason: str


_MUTATING_ACTIONS = frozenset({"click", "dblclick"})

# Patterns matched against the lowercased element name.
# Each entry is (compiled regex, human-readable category).
_HIGH_RISK_NAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Destructive / irreversible
    (re.compile(r"\bdelete\b"), "destructive"),
    (re.compile(r"\bremove\b"), "destructive"),
    (re.compile(r"\bdestroy\b"), "destructive"),
    (re.compile(r"\bterminate\b"), "destructive"),
    (re.compile(r"\bpurge\b"), "destructive"),
    (re.compile(r"\bdrop\b"), "destructive"),
    (re.compile(r"\bformat\b"), "destructive"),
    (re.compile(r"\berase\b"), "destructive"),
    (re.compile(r"\bwipe\b"), "destructive"),
    (re.compile(r"\brunrevocabl"), "destructive"),
    (re.compile(r"\birreversible\b"), "destructive"),
    # Financial / transactional
    (re.compile(r"\bpay\b"), "financial"),
    (re.compile(r"\bpurchase\b"), "financial"),
    (re.compile(r"\bbuy\b"), "financial"),
    (re.compile(r"\bcheckout\b"), "financial"),
    (re.compile(r"\bsubscribe\b"), "financial"),
    (re.compile(r"\bplace\s*order\b"), "financial"),
    (re.compile(r"\bconfirm\s*(payment|order|purchase)\b"), "financial"),
    (re.compile(r"\btransfer\s*(fund|money)\b"), "financial"),
    # Account / access
    (re.compile(r"\bdeactivat"), "account"),
    (re.compile(r"\bclose\s*account\b"), "account"),
    (re.compile(r"\bdelete\s*account\b"), "account"),
    (re.compile(r"\brevoke\b"), "account"),
    (re.compile(r"\bunsubscribe\b"), "account"),
    # Admin / infrastructure
    (re.compile(r"\bshutdown\b"), "admin"),
    (re.compile(r"\breboot\b"), "admin"),
    (re.compile(r"\brestart\b"), "admin"),
    (re.compile(r"\bdeploy\b"), "admin"),
    (re.compile(r"\brollback\b"), "admin"),
    (re.compile(r"\breset\b"), "admin"),
    (re.compile(r"\bfactory\s*reset\b"), "admin"),
    # Publishing / broadcast
    (re.compile(r"\bpublish\b"), "publish"),
    (re.compile(r"\bsend\s*to\s*all\b"), "publish"),
    (re.compile(r"\bbroadcast\b"), "publish"),
    (re.compile(r"\bannounce\b"), "publish"),
    # Chinese equivalents for i18n
    (re.compile(r"删除"), "destructive"),
    (re.compile(r"移除"), "destructive"),
    (re.compile(r"销毁"), "destructive"),
    (re.compile(r"清空"), "destructive"),
    (re.compile(r"终止"), "destructive"),
    (re.compile(r"付款"), "financial"),
    (re.compile(r"支付"), "financial"),
    (re.compile(r"购买"), "financial"),
    (re.compile(r"下单"), "financial"),
    (re.compile(r"注销"), "account"),
    (re.compile(r"停用"), "account"),
    (re.compile(r"发布"), "publish"),
    (re.compile(r"广播"), "publish"),
)

_HIGH_RISK_ROLES = frozenset({"alertdialog"})

_CATEGORY_LABELS: dict[str, str] = {
    "destructive": "Destructive action",
    "financial": "Financial transaction",
    "account": "Account modification",
    "admin": "Infrastructure operation",
    "publish": "Content publishing",
}


def classify_interaction_risk(action: str, ref_info: RefInfo) -> RiskVerdict:
    """Classify the risk of an element interaction based on semantic content.

    Only mutating actions (click, dblclick) on elements whose name or role
    signals a destructive/financial/admin operation are classified as HIGH.
    Read-only actions (hover, focus, scroll) are always SAFE.

    Args:
        action: The interaction action (click, fill, hover, ...).
        ref_info: ARIA metadata of the target element.

    Returns:
        RiskVerdict with level and human-readable reason.
    """
    if action not in _MUTATING_ACTIONS:
        return RiskVerdict(SemanticRiskLevel.SAFE, "")

    if ref_info.role in _HIGH_RISK_ROLES:
        return RiskVerdict(
            SemanticRiskLevel.HIGH,
            f"Interaction with alert dialog: [{ref_info.role}] \"{ref_info.name}\"",
        )

    name_lower = ref_info.name.lower()
    for pattern, category in _HIGH_RISK_NAME_PATTERNS:
        if pattern.search(name_lower):
            label = _CATEGORY_LABELS.get(category, category)
            return RiskVerdict(
                SemanticRiskLevel.HIGH,
                f"{label}: [{ref_info.role}] \"{ref_info.name}\"",
            )

    return RiskVerdict(SemanticRiskLevel.SAFE, "")
