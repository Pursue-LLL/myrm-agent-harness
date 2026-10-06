"""Deterministic zero-LLM rule extractor for memory facts.

Extracts high-signal operational facts from raw text, tool outputs, and configuration
snippets using compiled regular expressions, keyword graphs, and semantic patterns.
Requires zero external API calls or LLM tokens.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.zero_llm.types import (
    ExtractedRuleFact,
    FactCategory,
)

# ── Compiled Regular Expression Patterns ──────────────────────────────

# 1. Preferences & Prohibitions (EN + ZH)
_RE_PREFERENCE_EN = re.compile(
    r"\b(?:always|never|do not|don'?t|prefer|must|ensure to|stop)\s+([a-zA-Z0-9_\-\s]{3,40}?)\s+(?:to|over|instead of|as|when)\s+([a-zA-Z0-9_\-\s]{2,40})",
    re.IGNORECASE,
)
_RE_PROHIBITION_DIRECT = re.compile(
    r"\b(?:never|don'?t|do not|strictly forbid|disallow)\s+(?:use|using|call|modify|delete)\s+([a-zA-Z0-9_\-./]+)",
    re.IGNORECASE,
)
_RE_PREFERENCE_ZH = re.compile(
    r"(?:务必|必须|优先|千万不要|严禁|禁止|切勿|不要)(?:使用|调用|修改|删除|采用)?([^\s，。！？；]{2,30}?)(?:而非|而不是|作为|为准|即可|。|$)",
)

# 2. Configuration & Environment Variables
_RE_ENV_CONFIG = re.compile(
    r"(?m)^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,30})\s*=\s*([\"']?[^\"'\n\r\t#\s]{1,120}[\"']?)",
)
_RE_PORT_CONFIG = re.compile(
    r"\b(?:port|PORT|listening on)\s*[:= ]\s*([0-9]{2,5})\b",
)

# 3. Tool Outcomes & Commands
_RE_COMMAND_EXIT = re.compile(
    r"(?:command|task|process|execution)\s+(?:exited with code|failed with code|finished with code)\s+([0-9]+)",
    re.IGNORECASE,
)
_RE_TEST_SUMMARY = re.compile(
    r"([0-9]+)\s+passed(?:,\s*([0-9]+)\s+failed)?(?:,\s*([0-9]+)\s+skipped)?\s+in\s+([0-9.]+)s",
    re.IGNORECASE,
)

# 4. Architecture & Technical Decisions
_RE_DECISION_EN = re.compile(
    r"\b(?:decided to|chose to|opted for|agreed to|resolved to)\s+([a-zA-Z0-9_\-\s]{3,50}?)(?:\s+because|\s+for|\.|\;|$)",
    re.IGNORECASE,
)
_RE_DECISION_ZH = re.compile(
    r"(?:决定采用|选择使用|架构选型为|最终采用|定案为)\s*([^\s，。！？；]{2,40})",
)

# 5. Dependencies & Versioning
_RE_DEPENDENCY_SPEC = re.compile(
    r"(?m)^\s*[\"']?([a-zA-Z0-9_\-\.]{2,40})[\"']?\s*(?:==|>=|<=|~=|\^)\s*[\"']?([0-9a-zA-Z_\-\.]{1,20})[\"']?",
)

# 6. Named Technical Entities (FTS5, SQLite, JWT, RBAC, etc.)
_RE_ACRONYM_ENTITY = re.compile(
    r"\b([A-Z]{3,10}(?:[0-9]{1,2})?)\b",
)
_RE_PASCAL_ENTITY = re.compile(
    r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+){1,4})\b",
)


def _compute_fact_id(category: FactCategory, subject: str, predicate: str, object_value: str) -> str:
    """Generate a deterministic sha256 short hash for fact deduplication."""
    raw = f"{category.value}|{subject.strip().lower()}|{predicate.strip().lower()}|{object_value.strip().lower()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"fact-{digest[:12]}"


class ZeroLlmRuleExtractor:
    """Extracts facts deterministically with zero model invocation."""

    def __init__(self, min_confidence: float = 0.6) -> None:
        self.min_confidence = min_confidence

    def extract_from_text(
        self,
        text: str,
        turn_index: int = 0,
        source_file: str | None = None,
    ) -> list[ExtractedRuleFact]:
        """Extract all deterministic facts matching compiled regex families."""
        if not text or not text.strip():
            return []

        raw_facts: list[ExtractedRuleFact] = []

        # 1. Preferences & Prohibitions
        for match in _RE_PROHIBITION_DIRECT.finditer(text):
            target = match.group(1).strip()
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.PREFERENCE, target, "prohibited", "true"),
                    category=FactCategory.PREFERENCE,
                    subject=target,
                    predicate="is_strictly_prohibited",
                    object_value="forbidden",
                    confidence=0.95,
                    evidence_snippet=match.group(0),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        for match in _RE_PREFERENCE_EN.finditer(text):
            subj = match.group(1).strip()
            obj = match.group(2).strip()
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.PREFERENCE, subj, "preferred_over", obj),
                    category=FactCategory.PREFERENCE,
                    subject=subj,
                    predicate="preferred_relative_to",
                    object_value=obj,
                    confidence=0.85,
                    evidence_snippet=match.group(0),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        for match in _RE_PREFERENCE_ZH.finditer(text):
            val = match.group(1).strip()
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.PREFERENCE, val, "user_rule", "mandated"),
                    category=FactCategory.PREFERENCE,
                    subject=val,
                    predicate="mandated_by_user",
                    object_value="enforced",
                    confidence=0.90,
                    evidence_snippet=match.group(0),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        # 2. Config & Env
        for match in _RE_ENV_CONFIG.finditer(text):
            var_name = match.group(1).strip()
            var_val = match.group(2).strip().strip("'\"")
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.CONFIGURATION, var_name, "equals", var_val),
                    category=FactCategory.CONFIGURATION,
                    subject=var_name,
                    predicate="configured_value",
                    object_value=var_val,
                    confidence=0.95,
                    evidence_snippet=match.group(0).strip(),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        for match in _RE_PORT_CONFIG.finditer(text):
            port = match.group(1).strip()
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.CONFIGURATION, "service_port", "listens_on", port),
                    category=FactCategory.CONFIGURATION,
                    subject="service_port",
                    predicate="listens_on",
                    object_value=port,
                    confidence=0.88,
                    evidence_snippet=match.group(0).strip(),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        # 3. Tool Outcomes
        for match in _RE_COMMAND_EXIT.finditer(text):
            code = match.group(1).strip()
            status_desc = "succeeded" if code == "0" else "failed"
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.TOOL_OUTCOME, "command_process", "exited", code),
                    category=FactCategory.TOOL_OUTCOME,
                    subject="command_process",
                    predicate=status_desc,
                    object_value=f"exit_code_{code}",
                    confidence=0.92,
                    evidence_snippet=match.group(0),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        for match in _RE_TEST_SUMMARY.finditer(text):
            passed = match.group(1)
            duration = match.group(4)
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.TOOL_OUTCOME, "test_suite", "passed", passed),
                    category=FactCategory.TOOL_OUTCOME,
                    subject="test_suite",
                    predicate="execution_metric",
                    object_value=f"{passed}_passed_in_{duration}s",
                    confidence=0.95,
                    evidence_snippet=match.group(0),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        # 4. Decisions
        for match in _RE_DECISION_EN.finditer(text):
            decision = match.group(1).strip()
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.DECISION, "architecture", "decided", decision),
                    category=FactCategory.DECISION,
                    subject="architecture_decision",
                    predicate="adopted",
                    object_value=decision,
                    confidence=0.82,
                    evidence_snippet=match.group(0).strip(),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        for match in _RE_DECISION_ZH.finditer(text):
            decision_zh = match.group(1).strip()
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.DECISION, "architecture", "selected", decision_zh),
                    category=FactCategory.DECISION,
                    subject="architecture_decision",
                    predicate="selected",
                    object_value=decision_zh,
                    confidence=0.85,
                    evidence_snippet=match.group(0).strip(),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        # 5. Dependencies
        for match in _RE_DEPENDENCY_SPEC.finditer(text):
            pkg = match.group(1).strip()
            ver = match.group(2).strip()
            raw_facts.append(
                ExtractedRuleFact(
                    fact_id=_compute_fact_id(FactCategory.DEPENDENCY, pkg, "pinned_to", ver),
                    category=FactCategory.DEPENDENCY,
                    subject=pkg,
                    predicate="version_constraint",
                    object_value=ver,
                    confidence=0.88,
                    evidence_snippet=match.group(0).strip(),
                    source_turn_index=turn_index,
                    source_file=source_file,
                )
            )

        # 6. Entities (Top 10 max to prevent flooding)
        entity_count = 0
        seen_entities: set[str] = set()
        for match in _RE_ACRONYM_ENTITY.finditer(text):
            if entity_count >= 10:
                break
            acronym = match.group(1).strip()
            if acronym not in seen_entities and len(acronym) >= 3:
                seen_entities.add(acronym)
                entity_count += 1
                raw_facts.append(
                    ExtractedRuleFact(
                        fact_id=_compute_fact_id(FactCategory.ENTITY, acronym, "term", "present"),
                        category=FactCategory.ENTITY,
                        subject=acronym,
                        predicate="technical_acronym",
                        object_value=acronym,
                        confidence=0.70,
                        evidence_snippet=acronym,
                        source_turn_index=turn_index,
                        source_file=source_file,
                    )
                )

        return self._deduplicate_and_filter(raw_facts)

    def _deduplicate_and_filter(self, facts: Sequence[ExtractedRuleFact]) -> list[ExtractedRuleFact]:
        """Deduplicate facts by fact_id and discard those below min_confidence."""
        unique_map: dict[str, ExtractedRuleFact] = {}
        for fact in facts:
            if fact.confidence < self.min_confidence:
                continue
            if fact.fact_id not in unique_map or fact.confidence > unique_map[fact.fact_id].confidence:
                unique_map[fact.fact_id] = fact
        return list(unique_map.values())
