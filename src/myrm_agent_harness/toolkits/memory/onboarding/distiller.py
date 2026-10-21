"""Distiller extracting structured tech stack preferences, pitfalls, and project goals from sampled windows.

[INPUT]
- typing: List, Dict, Optional, Literal
- hashlib: sha256
- uuid: uuid4
- datetime: datetime, timezone
- re: Pattern extractors
- .models: FirstEncounterReport, InsightExtractedFact, OnboardingConversationWindow

[OUTPUT]
- OnboardingInsightDistiller: Distills structured insight facts and generates FirstEncounterReport.

[POS]
Harness framework insight distillation engine transforming lightweight sampled conversation windows
into structured personal tech profiles and onboarding welcome reports.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime

from .models import FirstEncounterReport, InsightExtractedFact, OnboardingConversationWindow

_PREFERENCE_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(?:prefer|use|stick to)\s+([a-zA-Z0-9_\-\.\+]+)"), "Prefers using {}"),
    (re.compile(r"(?i)\b(?:always use|strict)\s+([a-zA-Z0-9_\-\.\+]+)"), "Enforces strict {}"),
    (re.compile(r"(?i)\b(?:do not use|never use|avoid)\s+([a-zA-Z0-9_\-\.\+]+)"), "Avoids using {}"),
]

_PITFALL_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(?:fixed by|solution was|resolved by)\s+([^\.\n;]{10,80})"), "Resolved issue via: {}"),
    (
        re.compile(r"(?i)\b(?:got error|bug was|crash caused by|discovered pitfall:?|pitfall:?)\s+([^\.\n;]{10,80})"),
        "Discovered pitfall: {}",
    ),
    (
        re.compile(r"(?i)\b(?:be careful with|do not forget to|learned lesson:?)\s+([^\.\n;]{10,80})"),
        "Pitfall caution: {}",
    ),
]

_GOAL_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(?:building|implementing|working on|objective is to)\s+([^\.\n;]{10,80})"), "Active goal: {}"),
    (re.compile(r"(?i)\b(?:refactor|migrate|upgrade)\s+([^\.\n;]{10,80})"), "Active task: {}"),
]


class OnboardingInsightDistiller:
    """Distills sanitized conversation windows into categorized insight facts with SHA256 fingerprints."""

    @staticmethod
    def compute_fingerprint(category: str, summary: str) -> str:
        """Compute normalized SHA256 fingerprint for idempotent deduplication."""
        normalized = f"{category.strip().lower()}:{summary.strip().lower()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def distill_window(self, window: OnboardingConversationWindow) -> list[InsightExtractedFact]:
        """Extract structured insight facts from a single conversation window."""
        if not window.messages:
            return []

        facts: list[InsightExtractedFact] = []
        seen_fingerprints: set[str] = set()

        for msg in window.messages:
            text = msg.text
            # 1. Tech stack preferences
            for pattern, tmpl in _PREFERENCE_KEYWORDS:
                match = pattern.search(text)
                if match:
                    subject = match.group(1).strip()
                    summary = tmpl.format(subject)
                    fp = self.compute_fingerprint("tech_stack_preference", summary)
                    if fp not in seen_fingerprints:
                        seen_fingerprints.add(fp)
                        facts.append(
                            InsightExtractedFact(
                                fact_id=f"fact-{uuid.uuid4().hex[:8]}",
                                category="tech_stack_preference",
                                summary=summary,
                                source_agent=window.source_id,
                                confidence=0.88,
                                fingerprint=fp,
                                origin_conversation_id=window.conversation_id,
                                raw_quote=match.group(0)[:120],
                            )
                        )

            # 2. Hard learned lessons and pitfalls
            for pattern, tmpl in _PITFALL_KEYWORDS:
                match = pattern.search(text)
                if match:
                    subject = match.group(1).strip()
                    summary = tmpl.format(subject)
                    fp = self.compute_fingerprint("hard_learned_lesson", summary)
                    if fp not in seen_fingerprints:
                        seen_fingerprints.add(fp)
                        facts.append(
                            InsightExtractedFact(
                                fact_id=f"fact-{uuid.uuid4().hex[:8]}",
                                category="hard_learned_lesson",
                                summary=summary,
                                source_agent=window.source_id,
                                confidence=0.85,
                                fingerprint=fp,
                                origin_conversation_id=window.conversation_id,
                                raw_quote=match.group(0)[:120],
                            )
                        )

            # 3. Active project goals
            for pattern, tmpl in _GOAL_KEYWORDS:
                match = pattern.search(text)
                if match:
                    subject = match.group(1).strip()
                    summary = tmpl.format(subject)
                    fp = self.compute_fingerprint("active_project_goal", summary)
                    if fp not in seen_fingerprints:
                        seen_fingerprints.add(fp)
                        facts.append(
                            InsightExtractedFact(
                                fact_id=f"fact-{uuid.uuid4().hex[:8]}",
                                category="active_project_goal",
                                summary=summary,
                                source_agent=window.source_id,
                                confidence=0.82,
                                fingerprint=fp,
                                origin_conversation_id=window.conversation_id,
                                raw_quote=match.group(0)[:120],
                            )
                        )

        return facts

    def generate_report(
        self,
        windows: list[OnboardingConversationWindow],
    ) -> FirstEncounterReport:
        """Aggregate extracted facts across all windows and construct the FirstEncounterReport."""
        report_id = f"report-{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(UTC).isoformat()

        all_facts: list[InsightExtractedFact] = []
        global_fingerprints: dict[str, InsightExtractedFact] = {}
        probed_sources: set[str] = set()
        warnings: list[str] = []
        total_messages = 0

        for win in windows:
            probed_sources.add(win.source_id)
            total_messages += len(win.messages)
            if win.error:
                warnings.append(f"[{win.source_id}] {win.conversation_id}: {win.error}")
                continue

            extracted = self.distill_window(win)
            for fact in extracted:
                if fact.fingerprint not in global_fingerprints:
                    global_fingerprints[fact.fingerprint] = fact
                    all_facts.append(fact)

        return FirstEncounterReport(
            report_id=report_id,
            generated_at=now_iso,
            probed_sources=sorted(list(probed_sources)),
            scanned_session_count=len(windows),
            total_messages_sampled=total_messages,
            facts=all_facts,
            scrubbed_secret_count=0,
            warnings=warnings,
        )
