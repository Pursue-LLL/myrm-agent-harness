"""Two-Plane Prompt Injection Detector differentiating user-plane from data-plane attacks.

[INPUT]
- Text payload, plane type (USER_PLANE or DATA_PLANE)

[OUTPUT]
- Classification of injection attempt, threat severity, and detected signatures.

[POS]
Harness core security module inspired by Anthropic Commerce Agents (Split injection into two cases).
Detects indirect prompt injection planted in external data payloads.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from myrm_agent_harness.core.security.data_plane_defense.types import (
    DataPlaneThreatFinding,
    InjectionPlaneType,
)

# Indirect prompt injection signatures frequently embedded in data planes (reviews, web snippets, etc.)
_DATA_PLANE_INJECTION_RULES: tuple[tuple[str, str], ...] = (
    (r"\bignore\s+(?:all\s+)?previous\s+instructions\b", "Instruction override directive"),
    (r"\bdisregard\s+(?:all\s+)?prior\s+(?:prompts|rules|instructions)\b", "Prior rules disregard directive"),
    (r"\byou\s+are\s+now\s+(?:in\s+)?(?:developer|dan|unrestricted)\s+mode\b", "Persona hijack directive"),
    (r"\bforget\s+everything\s+(?:you\s+were\s+told|above)\b", "Context wipe directive"),
    (r"\bnew\s+system\s+prompt\s*:\b", "System prompt forgery directive"),
    (r"\boutput\s+the\s+(?:system\s+prompt|initial\s+instructions)\b", "System prompt leak attempt"),
    (r"\bgive\s+(?:all|everyone)\s+a?\s*\d+%\s*discount\b", "Business logic manipulation attempt"),
    (r"\btransfer\s+all\s+(?:funds|balance|money)\b", "Financial manipulation attempt"),
)

# User-plane direct jailbreak signatures
_USER_PLANE_JAILBREAK_RULES: tuple[tuple[str, str], ...] = (
    (r"\bdo\s+anything\s+now\b", "DAN jailbreak signature"),
    (r"\bbypass\s+all\s+safety\s+filters\b", "Safety filter bypass directive"),
    (r"\bpretend\s+you\s+have\s+no\s+restrictions\b", "Restriction removal directive"),
)


@dataclass(frozen=True, slots=True)
class PlaneDetectionResult:
    """Detection analysis outcome for a specific injection plane."""

    plane: InjectionPlaneType
    is_suspicious: bool
    risk_score: float  # 0.0 (benign) to 1.0 (confirmed injection)
    detected_rules: tuple[str, ...] = ()
    findings: tuple[DataPlaneThreatFinding, ...] = ()
    analyzed_at: float = field(default_factory=time.time)


class TwoPlaneInjectionDetector:
    """Evaluates text against independent rules for user plane vs data plane."""

    @classmethod
    def detect(
        cls,
        text: str,
        plane: InjectionPlaneType = InjectionPlaneType.DATA_PLANE,
    ) -> PlaneDetectionResult:
        """Scan text against threat signatures appropriate for the specified plane."""
        if not text or not text.strip():
            return PlaneDetectionResult(
                plane=plane,
                is_suspicious=False,
                risk_score=0.0,
                detected_rules=(),
                findings=(),
                analyzed_at=time.time(),
            )

        rules = (
            _DATA_PLANE_INJECTION_RULES
            if plane == InjectionPlaneType.DATA_PLANE
            else _USER_PLANE_JAILBREAK_RULES
        )

        detected: list[str] = []
        findings: list[DataPlaneThreatFinding] = []

        for pattern, description in rules:
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            if matches:
                detected.append(description)
                for m in matches:
                    findings.append(
                        DataPlaneThreatFinding(
                            threat_type="indirect_prompt_injection"
                            if plane == InjectionPlaneType.DATA_PLANE
                            else "direct_jailbreak",
                            pattern_matched=pattern,
                            raw_snippet=m.group(0),
                            sanitized_replacement="[flagged]",
                        )
                    )

        is_suspicious = len(detected) > 0
        score = min(1.0, len(detected) * 0.4) if is_suspicious else 0.0

        return PlaneDetectionResult(
            plane=plane,
            is_suspicious=is_suspicious,
            risk_score=score,
            detected_rules=tuple(detected),
            findings=tuple(findings),
            analyzed_at=time.time(),
        )
