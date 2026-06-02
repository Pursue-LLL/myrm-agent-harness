"""Configuration Loader

Loads synonym and typo correction mappings from YAML files.
Supports dynamic updates without code changes.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_EMPTY_RESULT: dict[str, dict[str, list[str]]] = {"english": {}, "chinese": {}, "typos": {}}


class ConfigLoader:
    """Loads search configuration from YAML files"""

    @staticmethod
    def load_synonyms(config_path: str | Path | None = None) -> dict[str, dict[str, list[str]]]:
        """Load synonym mappings from YAML

        [INPUT]

        [OUTPUT]
        Dictionary with 'english', 'chinese', 'typos' sections

        [POS]
        Loads external configuration for flexible synonym management.
        Falls back to empty dicts if file not found.
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config" / "synonyms.yaml"
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            logger.warning("Synonym config not found at %s, using empty mappings", config_path)
            return dict(_EMPTY_RESULT)

        try:
            with open(config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)

            if not isinstance(raw, dict):
                logger.warning("Synonym config at %s has unexpected format, using empty mappings", config_path)
                return dict(_EMPTY_RESULT)

            return {
                "english": raw.get("english", {}),
                "chinese": raw.get("chinese", {}),
                "typos": raw.get("typos", {}),
            }
        except Exception as e:
            logger.error("Failed to load synonym config from %s: %s", config_path, e)
            return dict(_EMPTY_RESULT)
