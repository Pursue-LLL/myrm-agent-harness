"""Outbound text and log redaction filter to neutralize credential exposure.

[INPUT]
- Raw string text (logs, stdout, agent transcripts, outgoing chat messages)

[OUTPUT]
- RedactedEgressFilter: Scrubs all matching credentials using safe masking
- redact_text

[POS]
Harness core security redactor. Prevents secrets from leaking into UI displays,
logs, or persistent transcripts by replacing them with masked diagnostics.
"""

from __future__ import annotations

import logging
import re

from myrm_agent_harness.core.security.git_leak_shield.patterns import (
    SECRET_PATTERNS,
    mask_secret_value,
)
from myrm_agent_harness.core.security.git_leak_shield.types import RedactionResult

logger = logging.getLogger(__name__)


class RedactedEgressFilter:
    """Masks secret patterns in outbound texts, transcripts, and logs."""

    @classmethod
    def redact_text(cls, text: str) -> RedactionResult:
        """Scan text and replace all detected credentials with masked equivalents."""
        if not text:
            return RedactionResult(redacted_text="", redactions_count=0, detected_types=[])

        scrubbed = text
        redactions_count = 0
        detected_types: set[str] = set()

        for secret_type, _, pattern in SECRET_PATTERNS:
            def _replacer(match: re.Match[str], st: str = secret_type) -> str:
                nonlocal redactions_count
                redactions_count += 1
                detected_types.add(st)
                return mask_secret_value(match.group(0))

            scrubbed = pattern.sub(_replacer, scrubbed)

        if redactions_count > 0:
            logger.info(
                "Redacted %d secret(s) in egress text: %s",
                redactions_count,
                ", ".join(sorted(detected_types)),
            )

        return RedactionResult(
            redacted_text=scrubbed,
            redactions_count=redactions_count,
            detected_types=sorted(detected_types),
        )
