"""Query Expansion Module

Orchestrates query enhancement through modular components:
- QueryNormalizer: Preprocessing (case, punctuation, underscores)
- TypoCorrector: Spelling correction
- SynonymExpander: Synonym and multilingual expansion

[POS]
Improves search robustness through a clean, modular pipeline.
"""

from __future__ import annotations

import logging

from .query_normalizer import QueryNormalizer
from .query_parser import QueryParser
from .synonym_expander import SynonymExpander
from .typo_corrector import TypoCorrector

logger = logging.getLogger(__name__)


class QueryExpander:
    """Orchestrates query expansion pipeline

    Coordinates normalization, typo correction, and synonym expansion.
    Adaptive strategy: skips synonym expansion for multilingual format queries.
    """

    def __init__(self) -> None:
        """Initialize query expansion pipeline"""
        self._normalizer = QueryNormalizer()
        self._typo_corrector = TypoCorrector()
        self._synonym_expander = SynonymExpander()
        self._parser = QueryParser()

    def expand(self, query: str) -> list[str]:
        """Expand query through adaptive pipeline

        [INPUT]

        [OUTPUT]
        List of expanded query variations (including original)

        [POS]
        Applies normalization, typo correction, and conditional synonym expansion.
        Adaptive strategy: skips synonym expansion if query is multilingual format
        (e.g., "火车票/railway/train"), as LLM already provides rich semantic terms.
        Logs each transformation step for observability.
        """
        if not query.strip():
            return [query]

        original_query = query

        # Step 1: Normalize (case, punctuation, underscores)
        normalized = self._normalizer.normalize(query)
        expanded_queries = [normalized]

        if normalized != original_query.lower().strip():
            logger.debug(" [QueryNormalization] '%s' -> '%s'", original_query, normalized)

        # Step 2: Correct typos
        corrected = self._typo_corrector.correct(normalized)
        if corrected != normalized:
            expanded_queries.append(corrected)
            logger.info(" [TypoCorrection] '%s' -> '%s'", normalized, corrected)

        # Step 3: Adaptive synonym expansion
        base_query = corrected if corrected != normalized else normalized

        #  Adaptive Strategy: Skip synonym expansion for multilingual format queries
        if self._parser.has_multilingual_format(original_query):
            logger.info(
                " [AdaptiveExpansion] Multilingual format detected in '%s' -> Skipping synonym expansion "
                "(LLM already provides rich semantic terms)",
                original_query,
            )
        else:
            # Single-keyword or simple query: apply synonym expansion
            synonym_variations = self._synonym_expander.expand(base_query)

            # Merge all variations (deduplicate)
            added_variations = 0
            for variation in synonym_variations:
                if variation not in expanded_queries:
                    expanded_queries.append(variation)
                    added_variations += 1

            if added_variations > 0:
                logger.info(
                    " [SynonymExpansion] '%s' -> +%d variations (total: %d)",
                    base_query,
                    added_variations,
                    len(expanded_queries),
                )

        # Limit to top 5 variations to avoid explosion
        final_queries = expanded_queries[:5]

        if len(final_queries) > 1:
            logger.info(
                " [QueryExpansion] '%s' -> %d variations: %s",
                original_query,
                len(final_queries),
                final_queries[:3],  # Show first 3 for brevity
            )

        return final_queries

    def preprocess(self, query: str) -> str:
        """Preprocess query

        [INPUT]

        [OUTPUT]
        Normalized query

        [POS]
        Convenience method that delegates to QueryNormalizer.
        """
        return self._normalizer.normalize(query)
