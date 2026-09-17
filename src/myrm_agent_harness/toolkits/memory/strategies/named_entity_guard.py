"""Deterministic named entity and critical technical identifier guard for memory consolidation.

[INPUT]
- source_texts: Sequence[str] (Raw source memory contents before consolidation)
- consolidated_text: str (Candidate merged/corrected memory content from LLM)
- op_action: str (Operation type: merge, correct, update_content)
- reasoning: str (LLM-provided explanation for the change)

[OUTPUT]
- CriticalEntityType: Enum of protected technical identifier categories
- CriticalEntity: Extracted structured technical entity token
- NamedEntityGuardVerdict: Deterministic pass/fail verdict with actionable diagnostics
- NamedEntityGuard: High-performance, zero-IO deterministic guard engine

[POS]
Harness memory strategy layer. Protects against LLM consolidation hallucinations,
silent technical entity loss (e.g. dropping port 5433 or altering IP/endpoint),
and unauthorized variable muting. Runs in <1ms without network calls.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)

# Common uppercase words to ignore when extracting environment variables
_EXCLUDED_UPPERCASE_WORDS: frozenset[str] = frozenset(
    {
        "HTTP",
        "HTTPS",
        "JSON",
        "REST",
        "GRPC",
        "NULL",
        "TRUE",
        "FALSE",
        "HTML",
        "INFO",
        "WARN",
        "ERROR",
        "DEBUG",
        "USER",
        "AGENT",
        "POST",
        "GET",
        "PUT",
        "DELETE",
        "PATCH",
        "HEAD",
        "OPTIONS",
        "UUID",
        "UTF8",
        "ASCII",
        "NONE",
        "TODO",
        "NOTE",
        "FIXME",
        "DONE",
    }
)

# Precompiled deterministic regex patterns
_PORT_PATTERN: re.Pattern[str] = re.compile(r"(?::|\bport\s*[:=]?\s*)(\d{2,5})\b", re.IGNORECASE)
_IP_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
_URL_PATTERN: re.Pattern[str] = re.compile(
    r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>,;。！？\(\)\[\]]+"
)
_ENV_VAR_PATTERN: re.Pattern[str] = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b")
_FILE_PATH_PATTERN: re.Pattern[str] = re.compile(
    r"(?:/[a-zA-Z0-9_.-]+){2,}|(?:\./[a-zA-Z0-9_.-]+)+|[a-zA-Z0-9_.-]+\.(?:py|json|yaml|yml|toml|env|sql|sh|ts|tsx|js|conf|cfg)\b"
)


class CriticalEntityType(StrEnum):
    """Categories of critical technical identifiers protected during consolidation."""

    PORT = "port"
    IP_ADDRESS = "ip_address"
    URL_DSN = "url_dsn"
    ENV_VAR = "env_var"
    FILE_PATH = "file_path"


@dataclass(frozen=True, slots=True)
class CriticalEntity:
    """A single extracted technical identifier requiring preservation."""

    entity_type: CriticalEntityType
    value: str
    raw: str


@dataclass(frozen=True, slots=True)
class NamedEntityGuardVerdict:
    """Result of deterministic entity guard evaluation."""

    is_valid: bool
    rejection_code: str | None = None
    missing_entities: tuple[CriticalEntity, ...] = ()
    reason: str = ""


class NamedEntityGuard:
    """Deterministic validator that inspects LLM consolidation candidates for critical identifier fidelity."""

    def __init__(self, *, strict_mode: bool = True) -> None:
        self._strict_mode = strict_mode

    def extract_entities(self, text: str) -> tuple[CriticalEntity, ...]:
        """Extract all critical technical entities from a text string with deduplication."""
        if not text:
            return ()

        entities: list[CriticalEntity] = []
        seen_keys: set[tuple[CriticalEntityType, str]] = set()

        def _add(etype: CriticalEntityType, val: str, raw_match: str) -> None:
            normalized_val = val.strip().lower() if etype != CriticalEntityType.ENV_VAR else val.strip()
            key = (etype, normalized_val)
            if key not in seen_keys:
                seen_keys.add(key)
                entities.append(CriticalEntity(entity_type=etype, value=val.strip(), raw=raw_match.strip()))

        # 1. URL / DSN (checked first to avoid false sub-matches)
        for match in _URL_PATTERN.finditer(text):
            raw = match.group(0).rstrip(".,;:!?'\")>")
            _add(CriticalEntityType.URL_DSN, raw, raw)

        # 2. IP Addresses
        for match in _IP_PATTERN.finditer(text):
            raw = match.group(0).rstrip(".,;:!?'\")>")
            _add(CriticalEntityType.IP_ADDRESS, raw, raw)

        # 3. Ports
        for match in _PORT_PATTERN.finditer(text):
            port_num = match.group(1)
            # Filter standard invalid port ranges (> 65535 or < 10)
            if port_num.isdigit() and 10 <= int(port_num) <= 65535:
                _add(CriticalEntityType.PORT, port_num, match.group(0))

        # 4. Environment Variables
        for match in _ENV_VAR_PATTERN.finditer(text):
            var_name = match.group(0).rstrip(".,;:!?'\")>")
            if var_name not in _EXCLUDED_UPPERCASE_WORDS and not var_name.isdigit():
                _add(CriticalEntityType.ENV_VAR, var_name, var_name)

        # 5. File Paths
        for match in _FILE_PATH_PATTERN.finditer(text):
            path_str = match.group(0).rstrip(".,;:!?'\")>")
            _add(CriticalEntityType.FILE_PATH, path_str, path_str)

        return tuple(entities)

    def verify_consolidation(
        self,
        *,
        source_texts: Sequence[str],
        consolidated_text: str,
        op_action: str = "merge",
        reasoning: str = "",
    ) -> NamedEntityGuardVerdict:
        """Assert that no critical technical entity is dropped or mutated without justification."""
        if not source_texts:
            return NamedEntityGuardVerdict(is_valid=True)

        # Aggregate entities across all source memories
        source_entities_map: dict[tuple[CriticalEntityType, str], CriticalEntity] = {}
        for src in source_texts:
            for ent in self.extract_entities(src):
                key = (ent.entity_type, ent.value.lower() if ent.entity_type != CriticalEntityType.ENV_VAR else ent.value)
                source_entities_map[key] = ent

        if not source_entities_map:
            # No high-entropy technical entities in source texts; guard automatically passes
            return NamedEntityGuardVerdict(is_valid=True)

        # Extract entities from the consolidated candidate
        candidate_entities = self.extract_entities(consolidated_text)
        candidate_keys = {
            (ent.entity_type, ent.value.lower() if ent.entity_type != CriticalEntityType.ENV_VAR else ent.value)
            for ent in candidate_entities
        }

        # Check for missing critical entities
        missing_entities: list[CriticalEntity] = []
        for key, ent in source_entities_map.items():
            if key not in candidate_keys:
                # Entity is absent in candidate output.
                # Check if it was explicitly mentioned/justified in reasoning (e.g. for correct ops)
                entity_mentioned_in_reasoning = ent.value.lower() in reasoning.lower()
                if op_action == "correct" and entity_mentioned_in_reasoning:
                    # Legitimate correction where user or LLM intentionally supersedes the old entity
                    continue

                missing_entities.append(ent)

        if not missing_entities:
            return NamedEntityGuardVerdict(is_valid=True)

        # Determine primary rejection code
        primary = missing_entities[0]
        rejection_code = f"CRITICAL_ENTITY_LOST_{primary.entity_type.name}"
        missing_summary = ", ".join(f"{m.entity_type.value}:{m.value}" for m in missing_entities)
        reason = (
            f"Consolidation rejected: {len(missing_entities)} critical technical entity/entities dropped "
            f"({missing_summary}) without explicit justification in reasoning."
        )

        return NamedEntityGuardVerdict(
            is_valid=False,
            rejection_code=rejection_code,
            missing_entities=tuple(missing_entities),
            reason=reason,
        )
