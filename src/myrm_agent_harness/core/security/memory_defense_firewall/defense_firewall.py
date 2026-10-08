"""Pre-Ingestion Memory Defense Firewall inspecting and sanitizing memory retain entries."""

from __future__ import annotations

import hashlib
import time
import uuid

from .pattern_catalog import CompiledPattern, get_compiled_patterns
from .types import (
    DefenseAction,
    DefensePolicy,
    DetectionMatch,
    MemoryDefenseResult,
    SensitiveCategory,
)


def _compute_fingerprint(content: str) -> str:
    """Generate SHA-256 hex digest for false-positive whitelist matching."""
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


class MemoryDefenseFirewall:
    """Pre-ingestion defense firewall inspecting and sanitizing content before memory storage.

    Enforces tri-state safety:
    - ALLOW: Clean or whitelisted text is admitted unmodified.
    - REDACT: Sensitive credentials/PII are masked in-place with specific tags.
    - BLOCK: Hostile prompt injections or untrusted secrets are completely refused.
    """

    def __init__(self, patterns: list[CompiledPattern] | None = None) -> None:
        self._patterns: list[CompiledPattern] = patterns or get_compiled_patterns()
        self._exemptions: set[str] = set()
        self._audit_records: list[MemoryDefenseResult] = []

    def add_exemption(self, token_or_content: str) -> None:
        """Add exact token or content hash to false-positive exemption whitelist."""
        clean = token_or_content.strip()
        if not clean:
            return
        self._exemptions.add(clean)
        self._exemptions.add(_compute_fingerprint(clean))

    def remove_exemption(self, token_or_content: str) -> bool:
        """Remove entry from exemption whitelist."""
        clean = token_or_content.strip()
        fp = _compute_fingerprint(clean)
        existed = (clean in self._exemptions) or (fp in self._exemptions)
        self._exemptions.discard(clean)
        self._exemptions.discard(fp)
        return existed

    def list_exemptions(self) -> list[str]:
        """List active exemption tokens and fingerprints."""
        return sorted(self._exemptions)

    def _is_exempted(self, text: str) -> bool:
        """Check if whole content or its fingerprint is exempted."""
        clean = text.strip()
        if clean in self._exemptions:
            return True
        fp = _compute_fingerprint(clean)
        return fp in self._exemptions

    def _scan_matches(self, text: str) -> list[DetectionMatch]:
        """Scan text against all compiled patterns and return non-overlapping matches."""
        raw_matches: list[DetectionMatch] = []
        for cp in self._patterns:
            spec = cp.spec
            for m in cp.compiled_regex.finditer(text):
                start, end = m.span()
                matched_val = m.group(0)
                # Check token-level exemption
                if matched_val.strip() in self._exemptions:
                    continue
                preview = matched_val if len(matched_val) <= 12 else f"{matched_val[:4]}...{matched_val[-4:]}"
                raw_matches.append(
                    DetectionMatch(
                        pattern_id=spec.pattern_id,
                        pattern_name=spec.name,
                        category=spec.category,
                        start=start,
                        end=end,
                        matched_preview=preview,
                        replacement_tag=spec.replacement_tag,
                    )
                )

        # Sort by start offset ascending
        raw_matches.sort(key=lambda m: (m.start, -m.end))

        # Filter overlapping intervals (keep earlier/longer)
        non_overlapping: list[DetectionMatch] = []
        last_end = -1
        for match in raw_matches:
            if match.start >= last_end:
                non_overlapping.append(match)
                last_end = match.end
        return non_overlapping

    def _redact_text(self, text: str, matches: list[DetectionMatch]) -> str:
        """Redact text in reverse order of intervals to preserve exact indexing."""
        if not matches:
            return text
        result_chars = list(text)
        # Reverse order substitution
        sorted_rev = sorted(matches, key=lambda m: m.start, reverse=True)
        for m in sorted_rev:
            result_chars[m.start : m.end] = list(m.replacement_tag)
        return "".join(result_chars)

    def inspect_and_defend(
        self,
        text: str,
        policy: DefensePolicy | None = None,
    ) -> MemoryDefenseResult:
        """Inspect inbound text and apply ALLOW, REDACT, or BLOCK action."""
        now = time.time()
        audit_id = f"mdf_{int(now)}_{uuid.uuid4().hex[:8]}"
        orig_len = len(text)

        # 1. Whole-content whitelist check
        if self._is_exempted(text):
            res = MemoryDefenseResult(
                action_taken=DefenseAction.ALLOW,
                is_admitted=True,
                sanitized_text=text,
                original_length=orig_len,
                sanitized_length=orig_len,
                matches=[],
                audit_id=audit_id,
                timestamp=now,
            )
            self._audit_records.append(res)
            return res

        # 2. Pattern detection
        matches = self._scan_matches(text)
        if not matches:
            res = MemoryDefenseResult(
                action_taken=DefenseAction.ALLOW,
                is_admitted=True,
                sanitized_text=text,
                original_length=orig_len,
                sanitized_length=orig_len,
                matches=[],
                audit_id=audit_id,
                timestamp=now,
            )
            self._audit_records.append(res)
            return res

        # 3. Policy evaluation
        effective_policy = policy or DefensePolicy(default_action=DefenseAction.REDACT)
        matched_categories: set[SensitiveCategory] = {m.category for m in matches}

        should_block = (
            effective_policy.default_action == DefenseAction.BLOCK
            or bool(matched_categories & effective_policy.blocked_categories)
        )

        if should_block:
            res = MemoryDefenseResult(
                action_taken=DefenseAction.BLOCK,
                is_admitted=False,
                sanitized_text="",
                original_length=orig_len,
                sanitized_length=0,
                matches=matches,
                audit_id=audit_id,
                timestamp=now,
            )
            self._audit_records.append(res)
            return res

        if effective_policy.default_action == DefenseAction.ALLOW:
            res = MemoryDefenseResult(
                action_taken=DefenseAction.ALLOW,
                is_admitted=True,
                sanitized_text=text,
                original_length=orig_len,
                sanitized_length=orig_len,
                matches=matches,
                audit_id=audit_id,
                timestamp=now,
            )
            self._audit_records.append(res)
            return res

        # 4. In-place redaction
        redacted = self._redact_text(text, matches)
        res = MemoryDefenseResult(
            action_taken=DefenseAction.REDACT,
            is_admitted=True,
            sanitized_text=redacted,
            original_length=orig_len,
            sanitized_length=len(redacted),
            matches=matches,
            audit_id=audit_id,
            timestamp=now,
        )
        self._audit_records.append(res)
        return res

    def get_audit_records(self, limit: int = 50) -> list[MemoryDefenseResult]:
        """Fetch historical audit evaluation entries."""
        if limit <= 0:
            return list(self._audit_records)
        return list(self._audit_records[-limit:])
