# [INPUT] PersonaFileKind, BadSmellCategory, AuditLineSmell, FileDriftAuditResult from .drift_types
# [OUTPUT] LineByLineRealityReconciler
# [POS] Core engine for line-by-line reality reconciliation and 4D memory bad-smell tagging (STALE, DUPLICATE, CONTRADICTORY, NO_OP)

"""Line-by-line reality reconciliation engine auditing persona and memory files."""

from __future__ import annotations

from pathlib import Path
import re

from .drift_types import (
    AuditLineSmell,
    BadSmellCategory,
    FileDriftAuditResult,
    PersonaFileKind,
)

# Common filler/chit-chat patterns that consume tokens without guiding behavior
NO_OP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:had a great chat|good conversation|we talked about|nice talking to you)", re.IGNORECASE),
    re.compile(r"(?:user was happy|user said thanks|user was satisfied)", re.IGNORECASE),
    re.compile(r"(?:i am an ai assistant|i am here to help|as an ai language model)", re.IGNORECASE),
    re.compile(r"(?:hello world|welcome to the project|looking forward to assisting)", re.IGNORECASE),
    re.compile(r"(?:today is|current date is|just logging this note)", re.IGNORECASE),
]

# Mutually contradictory pairs
CONTRADICTION_PAIRS: list[tuple[re.Pattern[str], re.Pattern[str], str]] = [
    (
        re.compile(r"\b(?:brief|concise|short)\b", re.IGNORECASE),
        re.compile(r"\b(?:detailed|exhaustive|elaborate|in-depth)\b", re.IGNORECASE),
        "Contradiction: demanding extreme brevity while also demanding exhaustive elaboration.",
    ),
    (
        re.compile(r"\b(?:tabs)\b", re.IGNORECASE),
        re.compile(r"\b(?:spaces)\b", re.IGNORECASE),
        "Contradiction: indentation rule conflict between tabs and spaces.",
    ),
    (
        re.compile(r"\b(?:functional)\b", re.IGNORECASE),
        re.compile(r"\b(?:object-oriented|oop)\b", re.IGNORECASE),
        "Contradiction: architectural conflict between pure functional and strict OOP.",
    ),
]


class LineByLineRealityReconciler:
    """Audits persona files line by line against reality and tags four dimensions of degradation."""

    @classmethod
    def audit_persona_file(
        cls,
        file_path: str,
        content: str,
        file_kind: PersonaFileKind = "UNKNOWN",
        workspace_root: Path | None = None,
    ) -> FileDriftAuditResult:
        """Scan file content line-by-line and emit flagged bad-smell flaws."""
        lines = content.splitlines()
        flagged_lines: list[AuditLineSmell] = []
        seen_normalized_statements: dict[str, int] = {}  # normalized text -> first seen line_num

        # Track patterns for contradiction detection
        active_rules: list[tuple[int, str]] = []  # (line_num, line_text)

        total_waste_chars = 0

        for line_idx, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Strip markdown list markers and punctuation for normalization
            clean_text = re.sub(r"^[-*+>\d.]+\s*", "", stripped).strip().lower()
            if len(clean_text) < 4:
                continue

            # 1. Detect NO_OP flaws (filler, chit-chat)
            is_no_op = False
            for pat in NO_OP_PATTERNS:
                if pat.search(clean_text):
                    smell = AuditLineSmell(
                        line_number=line_idx,
                        original_text=raw_line,
                        smell="NO_OP",
                        explanation="Conversational filler or journal log that consumes context without altering agent behavior.",
                        proposed_resolution="Prune entire line to save context budget.",
                        confidence=0.90,
                    )
                    flagged_lines.append(smell)
                    total_waste_chars += len(raw_line)
                    is_no_op = True
                    break

            if is_no_op:
                continue

            # 2. Detect DUPLICATE flaws (redundancy across lines)
            norm_key = re.sub(r"[^a-z0-9]", "", clean_text)
            if norm_key in seen_normalized_statements:
                first_line = seen_normalized_statements[norm_key]
                smell = AuditLineSmell(
                    line_number=line_idx,
                    original_text=raw_line,
                    smell="DUPLICATE",
                    explanation=f"Near-identical preference already declared at line {first_line}.",
                    proposed_resolution="Remove redundant duplication.",
                    confidence=0.85,
                )
                flagged_lines.append(smell)
                total_waste_chars += len(raw_line)
                continue
            else:
                seen_normalized_statements[norm_key] = line_idx

            # 3. Detect CONTRADICTORY flaws
            active_rules.append((line_idx, stripped))
            for pat_a, pat_b, explanation in CONTRADICTION_PAIRS:
                if pat_b.search(stripped):
                    # Check if any prior line matches pat_a
                    for prev_line_num, prev_text in active_rules[:-1]:
                        if pat_a.search(prev_text):
                            smell = AuditLineSmell(
                                line_number=line_idx,
                                original_text=raw_line,
                                smell="CONTRADICTORY",
                                explanation=f"{explanation} Clashes with line {prev_line_num}: '{prev_text}'.",
                                proposed_resolution="Reconcile policy with human confirmation.",
                                confidence=0.95,
                            )
                            flagged_lines.append(smell)
                            total_waste_chars += len(raw_line)
                            break

            # 4. Detect STALE flaws (file references not existing in workspace)
            if workspace_root is not None and workspace_root.is_dir():
                file_matches = re.findall(r"\b([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]{1,5})\b", stripped)
                for f_ref in file_matches:
                    if f_ref.startswith(("http://", "https://", "www.", "e.g.", "i.e.")):
                        continue
                    if f_ref.endswith((".config.js", ".config.ts", ".yml", ".yaml", ".json", ".sql", ".py")):
                        target_path = workspace_root / f_ref
                        if not target_path.exists():
                            smell = AuditLineSmell(
                                line_number=line_idx,
                                original_text=raw_line,
                                smell="STALE",
                                explanation=f"References workspace file '{f_ref}' which does not exist on disk.",
                                proposed_resolution="Update or remove outdated file reference.",
                                confidence=0.80,
                            )
                            flagged_lines.append(smell)
                            total_waste_chars += len(raw_line)
                            break

        # Calculate estimated token waste (~4 chars/token)
        estimated_tokens = max(0, total_waste_chars // 4)

        # Health score calculation (100 minus penalty)
        penalty = 0
        for f in flagged_lines:
            if f.smell == "CONTRADICTORY":
                penalty += 15
            elif f.smell == "STALE":
                penalty += 10
            elif f.smell == "DUPLICATE":
                penalty += 5
            elif f.smell == "NO_OP":
                penalty += 3
        healthy_score = max(0, min(100, 100 - penalty))

        return FileDriftAuditResult(
            file_path=file_path,
            file_kind=file_kind,
            total_lines=len(lines),
            flagged_lines=flagged_lines,
            estimated_token_waste=estimated_tokens,
            healthy_score=healthy_score,
        )
