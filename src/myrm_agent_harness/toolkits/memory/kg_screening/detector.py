"""Pattern-based threat detection and instruction sanitizer for knowledge graph inputs.

[INPUT]
- re
- toolkits.memory.kg_screening.types::ThreatCategory, ThreatFinding (POS: types)

[OUTPUT]
- PreExtractionContentScreeningDetector: Identifies hidden HTML instructions, zero-width steganography, system overrides, and data exfiltration patterns in text before graph extraction.

[POS]
Sub-millisecond regex & pattern scanner providing defense-in-depth against prompt injection and memory graph poisoning.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.kg_screening.types import (
    ThreatCategory,
    ThreatFinding,
)

# 1. Zero-width and hidden Unicode characters often used for invisible prompt injection
_ZERO_WIDTH_PATTERN = re.compile(r"[\u200B-\u200D\uFEFF\u202A-\u202E]")

# 2. Hidden HTML comments containing system commands or instructions
_HTML_COMMENT_INSTRUCTION_PATTERN = re.compile(
    r"<!--\s*(?:system|instruction|directive|override|eval|exec|admin|secret)[\s\S]*?-->",
    re.IGNORECASE,
)
_HTML_COMMENT_GENERIC_INJECTION_PATTERN = re.compile(
    r"<!--[\s\S]*?(?:ignore\s+all\s+previous|disregard|exfiltrate|override\s+rules)[\s\S]*?-->",
    re.IGNORECASE,
)

# 3. Explicit system prompt override markers
_SYSTEM_OVERRIDE_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "system_instruction_bracket",
        re.compile(r"\[(?:SYSTEM|ADMIN|DEVELOPER|ROOT)\s+(?:INSTRUCTION|OVERRIDE|DIRECTIVE|PROMPT)\]", re.IGNORECASE),
        "high",
    ),
    (
        "system_tag_injection",
        re.compile(r"<(?:system|admin|system_override|prompt_injection)>", re.IGNORECASE),
        "high",
    ),
    (
        "ignore_previous_instructions",
        re.compile(r"\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|prompts|rules|directives)\b", re.IGNORECASE),
        "high",
    ),
    (
        "human_assistant_spoofing",
        re.compile(r"(?:\n|^)(?:Human|User):\s*[\s\S]*?(?:\n|^)Assistant:\s*", re.IGNORECASE),
        "medium",
    ),
]

# 4. Data exfiltration patterns
_EXFILTRATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "curl_wget_exfil",
        re.compile(r"\b(?:curl|wget|fetch|axios)\s+.*?(?:attacker|webhook|exfiltrate|pastebin|ngrok)", re.IGNORECASE),
    ),
    (
        "secret_leak_instruction",
        re.compile(r"\b(?:send|exfiltrate|transmit)\s+(?:api[_\s]?key|secret|password|token)\s+to\s+https?://", re.IGNORECASE),
    ),
]


class PreExtractionContentScreeningDetector:
    """Detects and isolates prompt injection anomalies before text reaches graph extraction LLM."""

    def detect_findings(self, text: str) -> list[ThreatFinding]:
        """Scan input text against all defined security heuristic patterns."""
        findings: list[ThreatFinding] = []

        if not text:
            return findings

        # Check 1: Zero-width characters
        for match in _ZERO_WIDTH_PATTERN.finditer(text):
            char_hex = hex(ord(match.group(0)))
            findings.append(
                ThreatFinding(
                    category=ThreatCategory.ZERO_WIDTH_CHARACTER,
                    matched_pattern="zero_width_unicode",
                    snippet=f"U+{char_hex[2:].upper()}",
                    position=match.start(),
                    risk_level="medium",
                    description=f"Invisible Unicode character {char_hex} detected, potential steganographic injection.",
                )
            )

        # Check 2: Hidden HTML comment instructions
        for match in _HTML_COMMENT_INSTRUCTION_PATTERN.finditer(text):
            findings.append(
                ThreatFinding(
                    category=ThreatCategory.HIDDEN_HTML_INSTRUCTION,
                    matched_pattern="html_comment_system_directive",
                    snippet=match.group(0)[:60] + ("..." if len(match.group(0)) > 60 else ""),
                    position=match.start(),
                    risk_level="high",
                    description="Hidden HTML comment containing system/instruction keyword.",
                )
            )

        for match in _HTML_COMMENT_GENERIC_INJECTION_PATTERN.finditer(text):
            # Avoid duplicate if already caught
            if not any(f.position == match.start() for f in findings):
                findings.append(
                    ThreatFinding(
                        category=ThreatCategory.HIDDEN_HTML_INSTRUCTION,
                        matched_pattern="html_comment_injection_keyword",
                        snippet=match.group(0)[:60] + ("..." if len(match.group(0)) > 60 else ""),
                        position=match.start(),
                        risk_level="high",
                        description="Hidden HTML comment attempting rule override or exfiltration.",
                    )
                )

        # Check 3: Explicit system prompt override markers
        for pattern_name, pattern, risk in _SYSTEM_OVERRIDE_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(
                    ThreatFinding(
                        category=ThreatCategory.SYSTEM_PROMPT_OVERRIDE,
                        matched_pattern=pattern_name,
                        snippet=match.group(0)[:60],
                        position=match.start(),
                        risk_level=risk,
                        description=f"Explicit system override directive detected: '{pattern_name}'.",
                    )
                )

        # Check 4: Data exfiltration patterns
        for pattern_name, pattern in _EXFILTRATION_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(
                    ThreatFinding(
                        category=ThreatCategory.DATA_EXFILTRATION_PATTERN,
                        matched_pattern=pattern_name,
                        snippet=match.group(0)[:60],
                        position=match.start(),
                        risk_level="high",
                        description=f"Potential data exfiltration or external leak directive: '{pattern_name}'.",
                    )
                )

        return findings

    def sanitize_text(self, text: str) -> str:
        """Strip invisible zero-width characters and harmful HTML comment directives."""
        # Strip zero-width characters
        sanitized = _ZERO_WIDTH_PATTERN.sub("", text)

        # Strip comment injection blocks
        sanitized = _HTML_COMMENT_INSTRUCTION_PATTERN.sub("", sanitized)
        sanitized = _HTML_COMMENT_GENERIC_INJECTION_PATTERN.sub("", sanitized)

        # Normalize redundant spaces resulting from strip
        sanitized = re.sub(r"[ \t]+", " ", sanitized)
        return sanitized.strip()
