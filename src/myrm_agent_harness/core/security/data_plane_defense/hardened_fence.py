"""Hardened Data Fence neutralizing forged turn markers, control characters, and indirect injections.

[INPUT]
- raw external text, subject, source, max_fenced_chars

[OUTPUT]
- SanitizedQuoteResult: safely fenced and NFKC-normalized text enclosed in structural boundaries.

[POS]
Harness core security module inspired by Anthropic Commerce Agents (Fence.fence_payload & _strip_forged_turns).
"""

from __future__ import annotations

import re
import time
import unicodedata

from myrm_agent_harness.core.security.data_plane_defense.types import (
    DataPlaneThreatFinding,
    SanitizedQuoteResult,
)

# Invisible, zero-width, and forbidden control characters (excluding newline \n and tab \t)
_CONTROL_CHAR_REGEX: re.Pattern[str] = re.compile(
    r"[\u200b-\u200f\ufeff\u202a-\u202e\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)

# Forged turn markers used to hijack dialogue structure
_FORGED_TURNS_REGEX: re.Pattern[str] = re.compile(
    r"(?:\r?\n|^)[ \t]*(?:Human|User|Assistant|System|H|A)[ \t]*:[ \t]*",
    re.IGNORECASE,
)

# Special chat template tokens often injected to escape context
_SPECIAL_TOKENS_REGEX: re.Pattern[str] = re.compile(
    r"(?:<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|\[INST\]|\[/INST\]|<s>|</s>)",
    re.IGNORECASE,
)

_DEFAULT_MAX_FENCED_CHARS: int = 16000


class HardenedDataFence:
    """Sanitizes external third-party strings and encloses them in tamper-resistant delimiters."""

    @classmethod
    def fence_payload(
        cls,
        raw_text: str,
        subject: str = "untrusted_content",
        source: str = "external_tool",
        max_fenced_chars: int = _DEFAULT_MAX_FENCED_CHARS,
    ) -> SanitizedQuoteResult:
        """Sanitize raw text, neutralize prompt injections, and wrap in structured boundary tags."""
        if not raw_text:
            enclosed = f'<quoted_data subject="{subject}" source="{source}">\n\n</quoted_data>'
            return SanitizedQuoteResult(
                sanitized_text="",
                enclosed_payload=enclosed,
                subject=subject,
                source=source,
                original_length=0,
                sanitized_length=0,
                stripped_turns_count=0,
                removed_control_chars_count=0,
                is_truncated=False,
                findings=(),
                sanitized_at=time.time(),
            )

        original_len = len(raw_text)
        findings: list[DataPlaneThreatFinding] = []

        # 1. Unicode NFKC normalization
        normalized = unicodedata.normalize("NFKC", raw_text)

        # 2. Strip invisible and control characters
        control_matches = list(_CONTROL_CHAR_REGEX.finditer(normalized))
        removed_ctrl_count = len(control_matches)
        if removed_ctrl_count > 0:
            findings.append(
                DataPlaneThreatFinding(
                    threat_type="invisible_control_chars",
                    pattern_matched="control_char_range",
                    raw_snippet=f"{removed_ctrl_count} control character(s)",
                    sanitized_replacement="stripped",
                )
            )
            cleaned = _CONTROL_CHAR_REGEX.sub("", normalized)
        else:
            cleaned = normalized

        # 3. Neutralize special tokens (ChatML, Llama tokens)
        special_matches = list(_SPECIAL_TOKENS_REGEX.finditer(cleaned))
        if special_matches:
            for m in special_matches:
                findings.append(
                    DataPlaneThreatFinding(
                        threat_type="special_token_injection",
                        pattern_matched=m.group(0),
                        raw_snippet=m.group(0),
                        sanitized_replacement="[escaped_token]",
                    )
                )
            cleaned = _SPECIAL_TOKENS_REGEX.sub("[escaped_token]", cleaned)

        # 4. Neutralize forged turn markers
        turn_matches = list(_FORGED_TURNS_REGEX.finditer(cleaned))
        stripped_turns_count = len(turn_matches)
        if stripped_turns_count > 0:
            for tm in turn_matches:
                findings.append(
                    DataPlaneThreatFinding(
                        threat_type="forged_turn_marker",
                        pattern_matched=tm.group(0),
                        raw_snippet=tm.group(0).strip(),
                        sanitized_replacement="[quoted_turn_neutralized]",
                    )
                )

            def _replace_turn(match: re.Match[str]) -> str:
                matched_str = match.group(0)
                # Keep newline if present, but defang the role label
                prefix = "\n" if "\n" in matched_str else ""
                clean_label = matched_str.strip().replace(":", "")
                return f"{prefix}[quoted: {clean_label}]: "

            cleaned = _FORGED_TURNS_REGEX.sub(_replace_turn, cleaned)

        # 5. Length truncation
        is_truncated = False
        if len(cleaned) > max_fenced_chars:
            cleaned = cleaned[:max_fenced_chars] + "\n... [content truncated by hardened fence]"
            is_truncated = True

        sanitized_len = len(cleaned)
        enclosed_payload = (
            f'<quoted_data subject="{subject}" source="{source}">\n'
            f"{cleaned}\n"
            f"</quoted_data>"
        )

        return SanitizedQuoteResult(
            sanitized_text=cleaned,
            enclosed_payload=enclosed_payload,
            subject=subject,
            source=source,
            original_length=original_len,
            sanitized_length=sanitized_len,
            stripped_turns_count=stripped_turns_count,
            removed_control_chars_count=removed_ctrl_count,
            is_truncated=is_truncated,
            findings=tuple(findings),
            sanitized_at=time.time(),
        )
