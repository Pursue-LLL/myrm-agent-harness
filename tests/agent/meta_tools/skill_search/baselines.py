"""Baseline Search Engines for Comparison

Provides baseline search implementations:
- Random: Random ranking (lower bound)
- TF-IDF: Classic information retrieval baseline

These baselines help quantify the effectiveness of BM25 and Hybrid modes.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from myrm_agent_harness.agent.meta_tools.skills.search.types import SkillSearchResult

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata


class RandomSearchEngine:
    """Random baseline: randomly shuffle skills

    This provides a lower bound for search quality.
    Any reasonable search engine should significantly outperform random ranking.
    """

    def __init__(self, skills: list[SkillMetadata], seed: int = 42) -> None:
        """Initialize random search engine

        Args:
            skills: List of skills to search
            seed: Random seed for reproducibility
        """
        self._skills = list(skills)
        self._random = random.Random(seed)

    def search(self, query: str, top_k: int = 5) -> list[SkillSearchResult]:
        """Random search: shuffle and return top-K

        Args:
            query: Search query (ignored)
            top_k: Number of results to return

        Returns:
            Randomly shuffled top-K skills
        """
        shuffled = self._skills.copy()
        self._random.shuffle(shuffled)

        return [
            SkillSearchResult(name=skill.name, description=skill.description, score=1.0) for skill in shuffled[:top_k]
        ]


class TFIDFSearchEngine:
    """TF-IDF baseline: classic information retrieval

    Uses TF-IDF (Term Frequency-Inverse Document Frequency) with cosine similarity.
    This is a standard baseline in information retrieval research.
    """

    def __init__(self, skills: list[SkillMetadata]) -> None:
        """Initialize TF-IDF search engine

        Args:
            skills: List of skills to search
        """
        self._skills = list(skills)

        # Build TF-IDF index
        documents = [f"{skill.name} {skill.description}" for skill in self._skills]
        self._vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",  # Remove common English stop words
            max_features=1000,  # Limit vocabulary size
        )
        self._tfidf_matrix = self._vectorizer.fit_transform(documents)

    def search(self, query: str, top_k: int = 5) -> list[SkillSearchResult]:
        """TF-IDF search with cosine similarity

        Args:
            query: Search query
            top_k: Number of results to return

        Returns:
            Top-K skills ranked by TF-IDF cosine similarity
        """
        if not query.strip():
            return []

        # Vectorize query
        query_vector = self._vectorizer.transform([query])

        # Compute cosine similarity
        similarities = cosine_similarity(query_vector, self._tfidf_matrix)[0]

        # Get top-K indices
        top_indices = similarities.argsort()[-top_k:][::-1]

        # Build results
        results = []
        for idx in top_indices:
            if similarities[idx] > 0:  # Only return non-zero similarities
                skill = self._skills[idx]
                results.append(
                    SkillSearchResult(name=skill.name, description=skill.description, score=float(similarities[idx]))
                )

        return results
