"""Summary quality auditor with retry support.

Validates ``StructuredSummary`` output from the summarizer against three
quality gates (structure, entity retention, information density) and
provides retry guidance when the summary falls short.

[INPUT]
- schemas::StructuredSummary, (POS: Planner Schema Definitions)
- langchain_core.messages::BaseMessage (POS: Core message type definitions. All cross-channel communication data structures are defined here; zero I/O, pure data.)
- utils.text_utils::get_token_count (POS: Universal text utilities. Provides code-block-aware text processing for all channel implementations (mention extraction, link parsing, etc.).)

[OUTPUT]
- AuditResult: dataclass with pass/fail, issues, and entity stats
- audit_summary: run all three quality gates
- extract_key_entities: pull file paths, code identifiers, UUIDs, hashes, and API endpoints from messages

[POS]
Quality gate for the summarizer.  Runs *after* LLM generates a summary
and *before* the caller accepts it.  Zero LLM calls — pure heuristics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.text_utils import get_token_count
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from ..infra.schemas import StructuredSummary

logger = get_agent_logger(__name__)

_FILE_PATH_RE = re.compile(
    r"(?:^|[\s\"'`(])("
    r"(?:[\w./-]+/[\w.-]+\.[\w]{1,6})" # path/to/file.ext
    r"|(?:[\w.-]+\.(?:py|ts|tsx|js|jsx|rs|go|java|yaml|yml|json|toml|md|sql|sh|css|html))"
    r")"
)

_IDENT_RE = re.compile(r"(?:def|class|function|interface|type|const|let|var|struct|enum)\s+(\w{3,})")

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

_HASH_PREFIX_RE = re.compile(r"(?:sha256|sha1|md5):[0-9a-f]{8,}", re.IGNORECASE)

_API_ENDPOINT_RE = re.compile(r"/api/v\d+/\S+")

_NOISE_WORDS = frozenset(
    {
        "true",
        "false",
        "none",
        "null",
        "self",
        "this",
        "async",
        "await",
        "import",
        "from",
        "return",
        "print",
        "error",
        "test",
        "data",
        "index",
        "utils",
        "types",
        "config",
        "setup",
        "init",
    }
)

_MIN_ENTITY_LEN = 4

_ENTITY_RETENTION_THRESHOLD = 0.30
_MIN_DENSITY_RATIO = 0.05
_MAX_DENSITY_RATIO = 0.40
_MIN_GOAL_LEN = 10


@dataclass(frozen=True)
class AuditResult:
    """Quality audit result for a structured summary."""

    passed: bool
    issues: list[str] = field(default_factory=list)
    entity_total: int = 0
    entity_retained: int = 0
    missing_entities: list[str] = field(default_factory=list)

    @property
    def retention_rate(self) -> float:
        return self.entity_retained / self.entity_total if self.entity_total else 1.0


def extract_key_entities(messages: list[BaseMessage]) -> set[str]:
    """Extract file paths, code identifiers, UUIDs, hashes, and API endpoints from messages."""
    entities: set[str] = set()
    for msg in messages:
        text = msg.content if isinstance(msg.content, str) else ""
        for m in _FILE_PATH_RE.finditer(text):
            entities.add(m.group(1))
        for m in _IDENT_RE.finditer(text):
            entities.add(m.group(1))
        for m in _UUID_RE.finditer(text):
            entities.add(m.group(0))
        for m in _HASH_PREFIX_RE.finditer(text):
            entities.add(m.group(0))
        for m in _API_ENDPOINT_RE.finditer(text):
            entities.add(m.group(0))

    return {e for e in entities if len(e) >= _MIN_ENTITY_LEN and e.lower() not in _NOISE_WORDS}


def audit_summary(
    summary: StructuredSummary, original_messages: list[BaseMessage], *, entities: set[str] | None = None
) -> AuditResult:
    """Run all quality gates on a structured summary.

    Gates:
    1. Structure completeness — required fields non-empty
    2. Key-entity retention — file paths, code identifiers, UUIDs, hashes, API endpoints preserved
    3. Information density — summary token ratio within bounds

    Returns:
        AuditResult with ``passed=True`` if all gates pass.
    """
    issues: list[str] = []

    issues.extend(_check_structure(summary))

    if entities is None:
        entities = extract_key_entities(original_messages)

    retained, missing = _check_entity_retention(summary, entities)

    if entities and (retained / len(entities)) < _ENTITY_RETENTION_THRESHOLD:
        rate = retained / len(entities)
        issues.append(
            f"Entity retention {rate:.0%} ({retained}/{len(entities)}) "
            f"below {_ENTITY_RETENTION_THRESHOLD:.0%} threshold"
        )

    issues.extend(_check_density(summary, estimate_messages_tokens(original_messages)))

    passed = len(issues) == 0

    result = AuditResult(
        passed=passed,
        issues=issues,
        entity_total=len(entities),
        entity_retained=retained,
        missing_entities=missing[:10],
    )

    if passed:
        logger.warning(
            " Summary audit passed (entities: %d/%d, rate: %.0f%%)",
            retained,
            len(entities),
            result.retention_rate * 100,
        )
    else:
        logger.warning(" Summary audit FAILED: %s", "; ".join(issues))

    return result


def build_retry_guidance(result: AuditResult) -> str:
    """Build a guidance string to inject into the retry prompt."""
    parts: list[str] = []

    if result.missing_entities:
        sample = result.missing_entities[:8]
        parts.append(f"The previous summary missed these key entities — please include them: {', '.join(sample)}")

    for issue in result.issues:
        if "too sparse" in issue.lower():
            parts.append("The summary was too short. Include more detail.")
        elif "too verbose" in issue.lower():
            parts.append("The summary was too long. Be more concise.")
        elif "empty" in issue.lower():
            parts.append(f"Fix: {issue}")

    return "\n".join(parts) if parts else "Please improve the summary quality."


def _check_structure(summary: StructuredSummary) -> list[str]:
    issues: list[str] = []
    if not summary.user_goal or len(summary.user_goal.strip()) < _MIN_GOAL_LEN:
        issues.append("user_goal is empty or too short")
    if not summary.completed_actions:
        issues.append("completed_actions is empty")
    if not summary.last_action:
        issues.append("last_action is empty")
    return issues


def _check_entity_retention(summary: StructuredSummary, entities: set[str]) -> tuple[int, list[str]]:
    """Return (retained_count, missing_entities_list)."""
    if not entities:
        return 0, []

    # to_json() 已包含所有字段，再补充 list 字段的原始文本确保搜索完整
    search_text = " ".join(
        [
            summary.to_json(),
            " ".join(summary.files_modified),
            " ".join(summary.errors_and_fixes),
            " ".join(summary.constraints_and_preferences),
            " ".join(summary.resolved_questions),
            " ".join(summary.pending_user_asks),
            summary.active_task,
            summary.active_state,
        ]
    )

    missing: list[str] = []
    retained = 0
    for entity in entities:
        if entity in search_text:
            retained += 1
        else:
            missing.append(entity)

    return retained, missing


def _check_density(summary: StructuredSummary, original_tokens: int) -> list[str]:
    if original_tokens <= 0:
        return []

    summary_tokens = get_token_count(summary.to_json())
    ratio = summary_tokens / original_tokens

    issues: list[str] = []
    if ratio < _MIN_DENSITY_RATIO:
        issues.append(f"Summary too sparse: {ratio:.1%} of original (minimum {_MIN_DENSITY_RATIO:.0%})")
    if ratio > _MAX_DENSITY_RATIO:
        issues.append(f"Summary too verbose: {ratio:.1%} of original (maximum {_MAX_DENSITY_RATIO:.0%})")
    return issues
