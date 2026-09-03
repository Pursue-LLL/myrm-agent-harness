"""Structured subagent handover state and evidence types.

[INPUT]
None (pure data schema definitions)

[OUTPUT]
- HandoffFinding: Structured finding with supporting evidence and confidence level
- AgentHandoverState: Structured subagent handover state with findings, citations, and artifacts

[POS]
Subagent subsystem handover data contract. Defines the structured state passed between subagents and callers to prevent token explosion.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = [
    "HandoffFinding",
    "AgentHandoverState",
]


@dataclass(frozen=True, slots=True)
class HandoffFinding:
    """Structured finding with supporting evidence and confidence level."""

    finding: str
    evidence: str = ""
    confidence: str = "high"

    def to_dict(self) -> dict[str, str]:
        return {
            "finding": self.finding,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> HandoffFinding:
        raw_conf = str(data.get("confidence", "high")).strip().lower()
        confidence = raw_conf if raw_conf in ("high", "medium", "low") else "high"
        return cls(
            finding=str(data.get("finding", "")),
            evidence=str(data.get("evidence", "")),
            confidence=confidence,
        )


@dataclass(frozen=True, slots=True)
class AgentHandoverState:
    """Structured handover state from a completed subagent to its caller/successors.

    Prevents token explosion by passing this concise state instead of raw transcripts.
    """

    summary: str = ""
    findings: list[HandoffFinding] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    context_artifacts: list[str] = field(default_factory=list)
    task_completed: list[str] = field(default_factory=list)
    pending_todos: list[str] = field(default_factory=list)
    risks_or_notes: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
            "citations": self.citations,
            "artifact_refs": self.artifact_refs,
            "context_artifacts": self.context_artifacts,
            "task_completed": self.task_completed,
            "pending_todos": self.pending_todos,
            "risks_or_notes": self.risks_or_notes,
            "relevant_files": self.relevant_files,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> AgentHandoverState:
        def string_list(key: str) -> list[str]:
            value = data.get(key)
            if not isinstance(value, list):
                return []
            return [item for item in value if isinstance(item, str) and item.strip()]

        findings_raw = data.get("findings")
        findings: list[HandoffFinding] = []
        if isinstance(findings_raw, list):
            for item in findings_raw:
                if isinstance(item, dict):
                    findings.append(HandoffFinding.from_dict(item))
                elif isinstance(item, str) and item.strip():
                    findings.append(HandoffFinding(finding=item.strip()))

        summary_val = data.get("summary")
        summary_str = str(summary_val).strip() if summary_val is not None else ""

        return cls(
            summary=summary_str,
            findings=findings,
            citations=string_list("citations"),
            artifact_refs=string_list("artifact_refs"),
            context_artifacts=string_list("context_artifacts"),
            task_completed=string_list("task_completed"),
            pending_todos=string_list("pending_todos"),
            risks_or_notes=string_list("risks_or_notes"),
            relevant_files=string_list("relevant_files"),
        )
