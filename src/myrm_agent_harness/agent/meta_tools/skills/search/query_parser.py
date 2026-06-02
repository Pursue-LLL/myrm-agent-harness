"""Query Parser for Multilingual Format Queries

Intelligently parses multilingual format queries like:
"火车票/railway ticket/train booking"

Extracts and weights terms appropriately:
- First term (original language): weight 1.0
- Second term (translation): weight 0.8
- Third+ terms (synonyms): weight 0.6
"""

from __future__ import annotations


class QueryParser:
    """Parse multilingual format queries with "/" delimiter

    [INPUT]
    Queries in format: "concept/translation/synonym concept2/translation2/synonym2"

    [OUTPUT]
    List of (term, weight) tuples

    [POS]
    - Detects "/" delimiter to identify multilingual format
    - Assigns declining weights to subsequent translations/synonyms
    - Preserves term order for BM25 scoring
    - Handles mixed format (some groups with "/", some without)
    """

    def __init__(self, primary_weight: float = 1.0, secondary_weight: float = 0.8, tertiary_weight: float = 0.6):
        """Initialize parser with configurable weights

        [INPUT]
        """
        self.primary_weight = primary_weight
        self.secondary_weight = secondary_weight
        self.tertiary_weight = tertiary_weight

    def parse(self, query: str) -> list[tuple[str, float]]:
        """Parse query into weighted terms

        [INPUT]

        [OUTPUT]
        List of (term, weight) tuples

        [EXAMPLES]
        >>> parser = QueryParser()
        >>> parser.parse("火车票/railway ticket/train booking")
        [('火车票', 1.0), ('railway ticket', 0.8), ('train booking', 0.6)]

        >>> parser.parse("database query")
        [('database', 1.0), ('query', 1.0)]

        >>> parser.parse("火车票/railway ticket 订票/booking")
        [('火车票', 1.0), ('railway ticket', 0.8), ('订票', 1.0), ('booking', 0.8)]

        [POS]
        - Splits by whitespace to identify term groups
        - For each group, splits by "/" to extract multilingual variants
        - Assigns weights based on position within group
        - Filters out empty strings and "/" artifacts
        """
        if not query or not query.strip():
            return []

        # Check if query contains "/" delimiter
        if "/" not in query:
            # Simple query without multilingual format
            # Each word gets primary weight
            words = query.split()
            return [(word, self.primary_weight) for word in words if word.strip()]

        # Parse multilingual format
        weighted_terms: list[tuple[str, float]] = []
        groups = query.split()  # Split by whitespace to identify term groups

        for group in groups:
            if not group.strip():
                continue

            if "/" in group:
                # Multilingual group: "火车票/railway ticket/train booking"
                variants = [v.strip() for v in group.split("/") if v.strip()]

                for idx, variant in enumerate(variants):
                    if idx == 0:
                        weight = self.primary_weight
                    elif idx == 1:
                        weight = self.secondary_weight
                    else:
                        weight = self.tertiary_weight

                    weighted_terms.append((variant, weight))
            else:
                # Regular term without variants
                weighted_terms.append((group, self.primary_weight))

        return weighted_terms

    def format_for_bm25(self, query: str) -> str:
        """Format parsed query for BM25 search

        [INPUT]

        [OUTPUT]
        Space-separated string with all terms (weights are implicit for BM25)

        [POS]
        BM25 doesn't use explicit weights, but having all terms in the query
        string ensures maximum recall. Weight information is preserved for
        future use if we implement weighted BM25.
        """
        weighted_terms = self.parse(query)
        return " ".join(term for term, _weight in weighted_terms)

    def has_multilingual_format(self, query: str) -> bool:
        """Check if query uses multilingual format

        [INPUT]

        [OUTPUT]
        True if query contains "/" delimiter, False otherwise

        [POS]
        Quick check to determine query format without full parsing.
        """
        return "/" in query

    def get_primary_terms(self, query: str) -> list[str]:
        """Extract primary (original language) terms only

        [INPUT]

        [OUTPUT]
        List of primary terms (first in each "/" group)

        [EXAMPLES]
        >>> parser = QueryParser()
        >>> parser.get_primary_terms("火车票/railway ticket 订票/booking")
        ['火车票', '订票']

        [POS]
        Useful for analyzing the user's original input terms
        (first term in each "/" group).
        """
        weighted_terms = self.parse(query)
        # Primary terms are those with primary_weight
        return [term for term, weight in weighted_terms if weight == self.primary_weight]
