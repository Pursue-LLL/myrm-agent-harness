"""Topic drift detector assessing task milestone closure and cross-task semantic divergence.

Analyzes completed todos, conversation longevity, and prompt semantic distance to identify
when a session has drifted from its initial scope, preventing unbounded context inflation.

[INPUT]
- agent.context_management.topic_drift_fork.topic_drift_types::DriftSignalKind, TopicDriftEvaluation (POS:
  Data contracts and type definitions for topic drift demarcation and auto-renamed session forking.)

[OUTPUT]
- TopicDriftDetector: Heuristic detector assessing milestone completion and cross-domain semantic topic
  shifts.

[POS]
Topic drift detector assessing task milestone closure and cross-task semantic divergence.
"""

from __future__ import annotations

import re
from typing import Sequence

from .topic_drift_types import (
    DriftSignalKind,
    TopicDriftEvaluation,
)


class TopicDriftDetector:
    """Heuristic detector assessing milestone completion and cross-domain semantic topic shifts."""

    _DOMAIN_KEYWORDS: dict[str, set[str]] = {
        "database": {"sql", "postgres", "mysql", "migration", "query", "index", "table", "schema", "lock", "db"},
        "frontend": {"react", "css", "html", "component", "button", "tailwind", "ui", "dom", "modal", "page"},
        "devops": {"docker", "kubernetes", "deploy", "nginx", "ci", "github-actions", "aws", "terraform", "helm"},
        "auth": {"jwt", "oauth", "login", "password", "token", "session", "permission", "rbac", "user"},
        "documentation": {"readme", "docs", "guide", "tutorial", "markdown", "api-spec", "swagger"},
    }

    _EXPLICIT_TRANSITION_PATTERNS = re.compile(
        r"\b(?:now\s+let's\s+(?:switch|start)|moving\s+on\s+to|next\s+task|new\s+goal|换个任务|接下来(?:做|开发|写)|开始新任务)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        min_prolonged_turns: int = 12,
        min_prolonged_tokens: int = 14000,
    ) -> None:
        self.min_prolonged_turns = min_prolonged_turns
        self.min_prolonged_tokens = min_prolonged_tokens

    def evaluate_drift(
        self,
        session_id: str,
        current_tokens: int,
        turn_count: int,
        previous_topic: str,
        current_prompt: str,
        all_todos_completed: bool = False,
    ) -> TopicDriftEvaluation:
        """Inspect the dialogue state and determine whether topic drift warrants session forking."""
        detected_signals: list[DriftSignalKind] = []
        confidence_points = 0.0

        # 1. Check for prolonged session
        if turn_count >= self.min_prolonged_turns or current_tokens >= self.min_prolonged_tokens:
            detected_signals.append(DriftSignalKind.PROLONGED_SESSION)
            confidence_points += 0.25

        # 2. Check for milestone completion (e.g. todos completed)
        if all_todos_completed:
            detected_signals.append(DriftSignalKind.MILESTONE_COMPLETED)
            confidence_points += 0.35

        # 3. Check for explicit transition phrases
        if self._EXPLICIT_TRANSITION_PATTERNS.search(current_prompt):
            detected_signals.append(DriftSignalKind.EXPLICIT_TOPIC_CHANGE)
            confidence_points += 0.40

        # 4. Semantic domain divergence
        new_domain = self._classify_domain(current_prompt)
        prev_domain = self._classify_domain(previous_topic)
        if new_domain and prev_domain and new_domain != prev_domain:
            detected_signals.append(DriftSignalKind.SEMANTIC_SHIFT)
            confidence_points += 0.30

        total_confidence = min(1.0, confidence_points)
        is_drift = (
            DriftSignalKind.EXPLICIT_TOPIC_CHANGE in detected_signals
            or (total_confidence >= 0.60 and len(detected_signals) >= 2)
        )

        extracted_new_topic = new_domain.capitalize() if new_domain else current_prompt[:40].strip()

        reason = (
            f"Topic drift detected with confidence {total_confidence:.2f} "
            f"via signals: {[s.value for s in detected_signals]}."
            if is_drift
            else "Conversation is continuing within current scope."
        )

        return TopicDriftEvaluation(
            session_id=session_id,
            is_drift_detected=is_drift,
            confidence=round(total_confidence, 2),
            detected_signals=detected_signals,
            previous_topic=previous_topic,
            new_detected_topic=extracted_new_topic,
            current_tokens=current_tokens,
            turn_count=turn_count,
            reason=reason,
        )

    def _classify_domain(self, text: str) -> str | None:
        """Infer high-level engineering domain by token overlap."""
        tokens = set(re.findall(r"\b[a-zA-Z0-9_\-]+\b", text.lower()))
        best_domain: str | None = None
        max_overlap = 0

        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            overlap = len(tokens & keywords)
            if overlap > max_overlap:
                max_overlap = overlap
                best_domain = domain

        return best_domain if max_overlap > 0 else None
