"""Query Normalizer

Preprocesses search queries for consistent matching:
- Normalizes case (lowercasing)
- Removes special characters (preserving Chinese and alphanumeric)
- Replaces underscores with spaces for better tokenization
- Normalizes whitespace
"""

from __future__ import annotations

import re


class QueryNormalizer:
    """Query preprocessing for consistent matching"""

    def normalize(self, query: str) -> str:
        """Normalize query for better matching

        [INPUT]

        [OUTPUT]
        Normalized query

        [POS]
        Handles case normalization, punctuation removal, underscore replacement,
        and whitespace normalization.
        """
        query = query.strip().lower()
        # Replace underscores with spaces for better tokenization
        query = query.replace("_", " ")
        # Remove punctuation but preserve Chinese characters and alphanumeric
        query = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", query)
        # Normalize whitespace
        query = re.sub(r"\s+", " ", query).strip()
        return query
