"""Shannon entropy scanner for detecting high-entropy credential candidates.

[INPUT]
- math: log2
- collections: Counter
- re: Pattern matching for candidate tokens

[OUTPUT]
- ShannonEntropyInspector: Inspector identifying un-prefixed high-entropy credentials.

[POS]
Harness framework security toolkit for defending against zero-day secret leakage
in historical conversation log ingestion where tokens lack known prefixes.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_CANDIDATE_TOKEN_PATTERN = re.compile(r"\b[A-Za-z0-9+/=_\-]{24,}\b")

# Whitelist of common non-secret long keywords or hashes
_COMMON_NON_SECRETS = {
    "application/x-www-form-urlencoded",
    "Content-Security-Policy",
    "Access-Control-Allow-Origin",
    "multipart/form-data",
}


class ShannonEntropyInspector:
    """Calculates character entropy to detect un-prefixed secrets and cryptographic keys."""

    def __init__(self, entropy_threshold: float = 4.5, min_token_len: int = 24) -> None:
        self._threshold = entropy_threshold
        self._min_len = min_token_len

    @staticmethod
    def calculate_entropy(text: str) -> float:
        """Compute the Shannon entropy of the given character string in bits per char."""
        if not text:
            return 0.0
        length = len(text)
        counts = Counter(text)
        entropy = 0.0
        for count in counts.values():
            prob = count / length
            entropy -= prob * math.log2(prob)
        return entropy

    def inspect_text(self, text: str) -> list[tuple[str, float]]:
        """Identify high-entropy tokens likely representing cryptographic secrets.

        Returns a list of tuples containing (token, entropy_score).
        """
        if not text or len(text) < self._min_len:
            return []

        results: list[tuple[str, float]] = []
        for match in _CANDIDATE_TOKEN_PATTERN.finditer(text):
            token = match.group(0)
            if len(token) < self._min_len or token in _COMMON_NON_SECRETS:
                continue

            # Skip tokens with standard path delimiters or code identifiers
            if "/" in token or "." in token:
                continue

            # Ensure diversity of character types (mix of letters, digits, symbols)
            has_lower = any(c.islower() for c in token)
            has_upper = any(c.isupper() for c in token)
            has_digit = any(c.isdigit() for c in token)

            # A pure-lowercase word or pure-uppercase hex needs stricter check
            if not ((has_lower and has_upper) or (has_lower and has_digit) or (has_upper and has_digit)):
                continue

            score = self.calculate_entropy(token)
            if score >= self._threshold:
                results.append((token, round(score, 3)))

        return results

    def redact_high_entropy_tokens(self, text: str) -> tuple[str, int]:
        """Redact detected high-entropy credential tokens with a placeholder."""
        candidates = self.inspect_text(text)
        if not candidates:
            return text, 0

        redacted_text = text
        redacted_count = 0
        for token, _ in candidates:
            if token in redacted_text:
                redacted_text = redacted_text.replace(token, "[REDACTED_HIGH_ENTROPY_SECRET]")
                redacted_count += 1

        return redacted_text, redacted_count
