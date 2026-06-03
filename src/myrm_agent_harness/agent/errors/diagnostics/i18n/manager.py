"""Locale manager for error diagnostic internationalization.

Supports automatic locale detection with fallback to English.
"""

from __future__ import annotations

import locale as stdlib_locale
import logging
import os
from typing import Any

from .constants import REQUIRED_ERROR_TYPES

logger = logging.getLogger(__name__)


class LocaleManager:
    """Locale manager for error diagnostic internationalization.

    Supports automatic locale detection with fallback to English.
    """

    def __init__(self, default_locale: str = "en") -> None:
        self._default_locale = default_locale
        self._translations: dict[str, dict[str, Any]] = {}
        self._load_translations()

    def _load_translations(self) -> None:
        """Load all translation dictionaries and validate completeness."""
        import json
        from pathlib import Path

        locales_dir = (
            Path(__file__).parent.parent.parent.parent.parent.parent.parent.parent
            / "myrm-agent"
            / "myrm-agent-server"
            / "app"
            / "channels"
            / "i18n"
            / "locales"
        )

        for name in ["en", "zh-CN", "ja", "ko", "de"]:
            json_path = locales_dir / f"{name}.json"
            if json_path.exists():
                try:
                    with open(json_path, encoding="utf-8") as f:
                        flat_data = json.load(f)

                        # Unflatten the data
                        trans: dict[str, dict[str, Any]] = {}
                        for k, v in flat_data.items():
                            if k.startswith("cooldown_hint_"):
                                if "_cooldown_hint" not in trans:
                                    trans["_cooldown_hint"] = {}
                                sub_k = k.replace("cooldown_hint_", "")
                                trans["_cooldown_hint"][sub_k] = v
                                continue

                            if k.endswith("_resolution_steps"):
                                err_type = k.replace("_resolution_steps", "")
                                if err_type not in trans:
                                    trans[err_type] = {}
                                trans[err_type]["resolution_steps"] = v
                            elif k.endswith("_user_message"):
                                err_type = k.replace("_user_message", "")
                                if err_type not in trans:
                                    trans[err_type] = {}
                                trans[err_type]["user_message"] = v

                        self._translations[name] = trans
                        if name == "zh-CN":
                            self._translations["zh_cn"] = trans
                except Exception as e:
                    logger.warning("Failed to load JSON locale %s: %s", json_path, e)

        self._validate_translations()

    def detect_locale(self) -> str:
        """Detect user's locale from environment.

        Checks (in order):
        1. MYRM_LOCALE env var
        2. LC_ALL/LC_MESSAGES/LANG env vars
        3. stdlib locale.getlocale()
        4. Fallback to default_locale
        """
        if myrm_locale := os.getenv("MYRM_LOCALE"):
            return self._normalize_locale(myrm_locale)

        for env_var in ("LC_ALL", "LC_MESSAGES", "LANG"):
            if env_value := os.getenv(env_var):
                return self._normalize_locale(env_value)

        try:
            default_locale, _ = stdlib_locale.getlocale()
            if default_locale:
                return self._normalize_locale(default_locale)
        except Exception:
            pass

        return self._default_locale

    def _normalize_locale(self, loc: str) -> str:
        """Normalize locale string (e.g., 'zh_cn.UTF-8' -> 'zh-CN')."""
        if loc in ("C", "POSIX"):
            return self._default_locale

        loc = loc.split(".")[0]

        if "_" in loc:
            parts = loc.split("_")
            loc = f"{parts[0]}-{parts[1].upper()}"

        language_defaults = {
            "zh": "zh-CN",
            "ja": "ja",
            "ko": "ko",
            "de": "de",
            "fr": "fr",
            "es": "es",
            "pt": "pt-BR",
            "ru": "ru",
            "it": "it",
        }

        if loc in language_defaults:
            loc = language_defaults[loc]

        return loc

    def translate(
        self, error_type: str, key: str, locale: str | None = None, **params: Any
    ) -> str | list[str]:
        """Translate a diagnostic message.

        Args:
            error_type: Error type (e.g., "connection")
            key: Translation key (e.g., "user_message", "resolution_steps")
            locale: Target locale (None = auto-detect)
            **params: Template parameters

        Returns:
            Localized message string or list of strings (for resolution_steps)
        """
        if locale is None:
            locale = self.detect_locale()

        for fallback_locale in (locale, "en"):
            if fallback_locale in self._translations:
                translations = self._translations[fallback_locale]
                if error_type in translations:
                    error_translations = translations[error_type]
                    if key in error_translations:
                        template = error_translations[key]
                        if isinstance(template, list):
                            return [
                                self._safe_format(step, params) for step in template
                            ]
                        return self._safe_format(template, params)

        logger.warning(
            f"Translation missing: {error_type}.{key} for locale {locale}. "
            f"Available locales: {self.get_supported_locales()}"
        )
        if key == "resolution_steps":
            return []
        return f"[Missing translation: {error_type}.{key}]"

    def _validate_translations(self) -> None:
        """Validate that all required error types have complete translations."""
        for locale, translations in self._translations.items():
            if locale == "zh_cn":
                continue

            for error_type in REQUIRED_ERROR_TYPES:
                if error_type not in translations:
                    logger.warning(
                        f"Missing translation for error type '{error_type}' in locale '{locale}'"
                    )
                    continue

                error_trans = translations[error_type]
                if "user_message" not in error_trans:
                    logger.warning(
                        f"Missing 'user_message' for error type '{error_type}' in locale '{locale}'"
                    )
                if "resolution_steps" not in error_trans:
                    logger.warning(
                        f"Missing 'resolution_steps' for error type '{error_type}' in locale '{locale}'"
                    )

    def _safe_format(self, template: str, params: dict[str, Any]) -> str:
        """Safely format template with parameters, using empty string for missing params."""
        try:
            return template.format(**params)
        except KeyError as e:
            missing_key = str(e).strip("'")
            params_with_fallback = {**params, missing_key: ""}
            return self._safe_format(template, params_with_fallback)

    def register_translations(
        self, locale: str, translations: dict[str, dict[str, str | list[str]]]
    ) -> None:
        """Register or merge custom translations for a locale."""
        existing = self._translations.get(locale)
        if existing is not None:
            for error_type, msgs in translations.items():
                existing[error_type] = msgs
        else:
            self._translations[locale] = translations
        logger.info(f"Registered translations for locale '{locale}'")

    def get_supported_locales(self) -> list[str]:
        """Get list of supported locales."""
        return [loc for loc in self._translations if loc != "zh_cn"]
