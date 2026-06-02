"""Typo Corrector

Fast dictionary-based spelling correction for common technical term typos.
Loads corrections from external YAML configuration.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import ClassVar

from .config_loader import ConfigLoader

logger = logging.getLogger(__name__)


class TypoCorrector:
    """Dictionary-based typo correction for technical terms"""

    # Common typos and corrections
    CORRECTIONS: ClassVar[dict[str, str]] = {
        "databse": "database",
        "databas": "database",
        "postgre": "postgres",
        "postgress": "postgres",
        "kubernets": "kubernetes",
        "kubernete": "kubernetes",
        "javascirpt": "javascript",
        "pytohn": "python",
        "authentification": "authentication",
        "authentcation": "authentication",
        "autentication": "authentication",
        "wether": "weather",
        "mesage": "message",
        "dock": "docker",
        "k8": "k8s",
        "piao": "票",
        "tianqi": "天气",
    }

    def __init__(self, config_path: str | Path | None = None) -> None:
        """Initialize typo corrector

        [INPUT]

        [POS]
        Loads typo corrections from external YAML config if available.
        Falls back to hardcoded CORRECTIONS if config not found.
        """
        # Try loading from external config first
        config = ConfigLoader.load_synonyms(config_path)

        if config["typos"]:
            # Use external config
            self._corrections = config["typos"]
            logger.info(" Loaded %d typo corrections from external config", len(self._corrections))
        else:
            # Fallback to hardcoded
            self._corrections = self.CORRECTIONS
            logger.warning(" Using hardcoded typo corrections (%d total)", len(self._corrections))

    def correct(self, query: str) -> str:
        """Correct common typos in query

        [INPUT]

        [OUTPUT]
        Corrected query

        [POS]
        Uses dictionary for fast, accurate correction.
        Returns original query if no typos found.
        """
        words = re.findall(r"\w+", query)
        corrected_words = [self._corrections.get(word, word) for word in words]

        if corrected_words != words:
            return " ".join(corrected_words)

        return query
