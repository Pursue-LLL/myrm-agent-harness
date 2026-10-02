"""Semantic element risk classification — cross-channel destructive control lexicon.

Classifies a GUI control (role + name) as high-risk when its semantic content
signals a destructive / financial / account / admin / publishing operation.
Shared SSOT consumed by every agent-facing GUI channel (browser DOM refs and
desktop AX element refs), so a mutating activation on a dangerous control is
gated identically regardless of which interaction toolkit performs it.

[INPUT]
- (none — pure standard library)

[OUTPUT]
- SemanticRiskLevel, RiskVerdict
- classify_element_risk: (role, name) → risk level + human-readable reason

[POS]
Pure function module — no side effects, no I/O, no channel-specific action
semantics (each toolkit layers its own mutating-action preconditions on top).
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple


class SemanticRiskLevel(Enum):
    SAFE = "safe"
    HIGH = "high"


class RiskVerdict(NamedTuple):
    level: SemanticRiskLevel
    reason: str


# Patterns matched against the lowercased element name.
# Each entry is (compiled regex, human-readable category).
_HIGH_RISK_ELEMENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
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

# Roles that themselves denote a high-risk surface regardless of name text.
_HIGH_RISK_ROLES = frozenset({"alertdialog"})

_CATEGORY_LABELS: dict[str, str] = {
    "destructive": "Destructive action",
    "financial": "Financial transaction",
    "account": "Account modification",
    "admin": "Infrastructure operation",
    "publish": "Content publishing",
}


def classify_element_risk(role: str, name: str) -> RiskVerdict:
    """Classify a GUI control by role + name against the destructive lexicon.

    Args:
        role: Element role identifier (ARIA role for web, AX/UIA role for desktop).
        name: Element name / accessible label text.

    Returns:
        RiskVerdict with level and a human-readable reason on HIGH match.
    """
    if role in _HIGH_RISK_ROLES:
        return RiskVerdict(
            SemanticRiskLevel.HIGH,
            f'Interaction with alert dialog: [{role}] "{name}"',
        )

    name_lower = name.lower()
    for pattern, category in _HIGH_RISK_ELEMENT_PATTERNS:
        if pattern.search(name_lower):
            label = _CATEGORY_LABELS.get(category, category)
            return RiskVerdict(
                SemanticRiskLevel.HIGH,
                f'{label}: [{role}] "{name}"',
            )

    return RiskVerdict(SemanticRiskLevel.SAFE, "")
