"""Attention dilution guard inspecting rule line count against the 200-line limit.

[INPUT]
- AttentionAuditReport: Audit report contract from rule_types.

[OUTPUT]
- audit_rule_attention_health: Evaluates a single rule file against attention dilution bounds.
- batch_audit_rules: Audits a collection of rule documents and produces diagnostic reports.

[POS]
Quality guardrail preventing monolithic rule bloat that degrades LLM adherence.
"""

from __future__ import annotations

import os
from typing import Mapping, Sequence

from .rule_types import AttentionAuditReport

DEFAULT_MAX_LINE_THRESHOLD = 200


def audit_rule_attention_health(
    file_path: str,
    content: str,
    max_lines: int = DEFAULT_MAX_LINE_THRESHOLD,
) -> AttentionAuditReport:
    """Evaluate whether a rule file exceeds the 200-line attention preservation threshold.

    Studies show that LLM adherence to rules degrades exponentially as individual
    rule files exceed 200 lines. Monolithic files cause rule dilution and compliance failures.

    Risk score is normalized:
    - 0.0: <= max_lines
    - 0.1 ~ 1.0: proportional excess beyond max_lines
    """
    lines = content.splitlines()
    line_count = len(lines)
    is_diluted = line_count > max_lines

    if not is_diluted:
        risk_score = 0.0
        recommendation = None
    else:
        excess = line_count - max_lines
        # Excess of 200 lines beyond threshold reaches max risk 1.0
        risk_score = round(min(1.0, excess / float(max_lines)), 2)
        recommendation = (
            f"Rule file '{os.path.basename(file_path)}' has {line_count} lines, "
            f"exceeding the {max_lines}-line attention limit. Decompose into focused "
            f"sub-rules in '.myrm/rules/<domain>.md' using 'paths' frontmatter scoping."
        )

    return AttentionAuditReport(
        file_path=file_path,
        line_count=line_count,
        is_diluted=is_diluted,
        risk_score=risk_score,
        split_recommendation=recommendation,
    )


def batch_audit_rules(
    rule_contents: Mapping[str, str],
    max_lines: int = DEFAULT_MAX_LINE_THRESHOLD,
) -> list[AttentionAuditReport]:
    """Audit multiple rule documents in batch."""
    reports: list[AttentionAuditReport] = []
    for file_path, content in rule_contents.items():
        reports.append(audit_rule_attention_health(file_path, content, max_lines))
    return reports
