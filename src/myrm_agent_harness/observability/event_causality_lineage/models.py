"""[INPUT] External event triggers (webhooks, MCP events, crons), matched rules, agent actions, and artifact diffs.
[OUTPUT] Immutable data structures for event-driven causality lineage tracking and reverse file change attribution.
[POS] myrm_agent_harness.observability.event_causality_lineage.models

Defines models for end-to-end causality chains:
1. ExternalEventTrigger: External event metadata (source, ID, payload summary).
2. CausalityRuleMatch: Automation policy and matched conditions.
3. AgentActionNode: Rationale, tool calls, latency, and token consumption.
4. ArtifactChangeRecord: Modified files, diff summaries, and commit references.
5. CausalityLineageRecord: End-to-end DAG linking event -> rule -> agent -> actions -> artifacts.
6. FileAttributionResult: Reverse lookup resolving a file back to its triggering external event.
"""

from dataclasses import dataclass, field
import time


@dataclass(frozen=True)
class ExternalEventTrigger:
    """External root event triggering agent execution."""

    event_id: str
    source_type: str  # e.g. "github_webhook", "slack_mention", "mcp_event", "cron"
    event_name: str
    payload_summary: str
    received_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int]:
        return {
            "event_id": self.event_id,
            "source_type": self.source_type,
            "event_name": self.event_name,
            "payload_summary": self.payload_summary,
            "received_at_ms": self.received_at_ms,
        }


@dataclass(frozen=True)
class CausalityRuleMatch:
    """Automation policy rule matched by the trigger event."""

    rule_id: str
    rule_name: str
    matched_condition: str

    def to_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "matched_condition": self.matched_condition,
        }


@dataclass(frozen=True)
class AgentActionNode:
    """Individual cognitive decision and execution step performed by the agent."""

    action_id: str
    agent_role: str
    decision_rationale: str
    tool_name: str
    input_summary: str
    duration_ms: float
    tokens_consumed: int
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | float | int]:
        return {
            "action_id": self.action_id,
            "agent_role": self.agent_role,
            "decision_rationale": self.decision_rationale,
            "tool_name": self.tool_name,
            "input_summary": self.input_summary,
            "duration_ms": round(self.duration_ms, 1),
            "tokens_consumed": self.tokens_consumed,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(frozen=True)
class ArtifactChangeRecord:
    """File modification, configuration change, or git commit produced by the agent."""

    file_path: str
    change_type: str  # "created", "modified", "deleted"
    diff_summary: str
    commit_sha: str = ""
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int]:
        return {
            "file_path": self.file_path,
            "change_type": self.change_type,
            "diff_summary": self.diff_summary,
            "commit_sha": self.commit_sha,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(frozen=True)
class CausalityLineageRecord:
    """Complete end-to-end event-to-artifact causality lineage DAG."""

    causality_trace_id: str
    session_id: str
    trigger: ExternalEventTrigger
    rule: CausalityRuleMatch
    agent_role: str
    actions: tuple[AgentActionNode, ...]
    artifacts: tuple[ArtifactChangeRecord, ...]
    total_tokens: int
    total_duration_ms: float
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int | float | dict[str, str | int] | dict[str, str] | list[dict[str, str | float | int]] | list[dict[str, str | int]]]:
        return {
            "causality_trace_id": self.causality_trace_id,
            "session_id": self.session_id,
            "trigger": self.trigger.to_dict(),
            "rule": self.rule.to_dict(),
            "agent_role": self.agent_role,
            "actions": [a.to_dict() for a in self.actions],
            "artifacts": [art.to_dict() for art in self.artifacts],
            "total_tokens": self.total_tokens,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "created_at_ms": self.created_at_ms,
        }


@dataclass(frozen=True)
class FileAttributionResult:
    """Reverse lookup result mapping a workspace file change back to its triggering external event."""

    file_path: str
    causality_trace_id: str
    trigger_event_id: str
    source_type: str
    event_name: str
    agent_role: str
    change_record: ArtifactChangeRecord
    rationale: str
    occurred_at_ms: int

    def to_dict(self) -> dict[str, str | int | dict[str, str | int]]:
        return {
            "file_path": self.file_path,
            "causality_trace_id": self.causality_trace_id,
            "trigger_event_id": self.trigger_event_id,
            "source_type": self.source_type,
            "event_name": self.event_name,
            "agent_role": self.agent_role,
            "change_record": self.change_record.to_dict(),
            "rationale": self.rationale,
            "occurred_at_ms": self.occurred_at_ms,
        }
