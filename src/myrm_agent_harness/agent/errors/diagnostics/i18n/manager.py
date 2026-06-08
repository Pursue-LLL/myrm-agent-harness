"""Locale manager for error diagnostic internationalization.

Supports automatic locale detection with fallback to English.

[INPUT]
- constants::REQUIRED_ERROR_TYPES (POS: Required error types for translation completeness validation)

[OUTPUT]
- LocaleManager: Locale detection, bundled JSON locale loading, and message formatting

[POS]
Framework-level i18n for LLM error diagnostics. Loads bundled locale JSON from the
package; override directory via MYRM_LOCALES_DIR. Business layers may extend via
register_translations().
"""

from __future__ import annotations

import json
import locale as stdlib_locale
import logging
import os
from pathlib import Path

from .constants import REQUIRED_ERROR_TYPES

logger = logging.getLogger(__name__)

_BUNDLED_LOCALES_DIR = Path(__file__).parent / "locales"
_SUPPORTED_LOCALE_NAMES = ("en", "zh-CN", "ja", "ko", "de")
ErrorFields = dict[str, str | list[str]]
LocaleBundle = dict[str, ErrorFields]


def _resolve_locales_dir() -> Path:
    """Resolve locale JSON directory: MYRM_LOCALES_DIR override, else bundled package data."""
    override = os.environ.get("MYRM_LOCALES_DIR", "").strip()
    if override:
        return Path(override)
    return _BUNDLED_LOCALES_DIR


def _unflatten_locale_json(flat_data: dict[str, object]) -> LocaleBundle:
    """Convert flat server-style locale keys into nested error_type -> field maps."""
    trans: LocaleBundle = {}
    for key, value in flat_data.items():
        if key.startswith("cooldown_hint_"):
            trans.setdefault("_cooldown_hint", {})[key.replace("cooldown_hint_", "")] = str(value)
            continue

        if key.endswith("_resolution_steps"):
            err_type = key.replace("_resolution_steps", "")
            if isinstance(value, list):
                trans.setdefault(err_type, {})["resolution_steps"] = [str(step) for step in value]
        elif key.endswith("_user_message"):
            err_type = key.replace("_user_message", "")
            trans.setdefault(err_type, {})["user_message"] = str(value)

    return trans


class LocaleManager:
    """Locale manager for error diagnostic internationalization.

    Supports automatic locale detection with fallback to English.
    """

    def __init__(self, default_locale: str = "en") -> None:
        self._default_locale = default_locale
        self._translations: dict[str, LocaleBundle] = {}
        self._load_translations()

    def _load_translations(self) -> None:
        """Load locale JSON files from the resolved locales directory."""
        locales_dir = _resolve_locales_dir()

        for name in _SUPPORTED_LOCALE_NAMES:
            json_path = locales_dir / f"{name}.json"
            if not json_path.exists():
                continue
            try:
                with open(json_path, encoding="utf-8") as f:
                    flat_data: dict[str, object] = json.load(f)
                trans = _unflatten_locale_json(flat_data)
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
        self,
        error_type: str,
        key: str,
        locale: str | None = None,
        **params: object,
    ) -> str | list[str]:
        """Translate a diagnostic message."""
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
                            return [self._safe_format(step, params) for step in template]
                        return self._safe_format(str(template), params)

        logger.warning(
            "Translation missing: %s.%s for locale %s. Available locales: %s",
            error_type,
            key,
            locale,
            self.get_supported_locales(),
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
                    logger.warning("Missing translation for error type '%s' in locale '%s'", error_type, locale)
                    continue

                error_trans = translations[error_type]
                if "user_message" not in error_trans:
                    logger.warning("Missing 'user_message' for error type '%s' in locale '%s'", error_type, locale)
                if "resolution_steps" not in error_trans:
                    logger.warning(
                        "Missing 'resolution_steps' for error type '%s' in locale '%s'", error_type, locale
                    )

    def _safe_format(self, template: str, params: dict[str, object]) -> str:
        """Safely format template with parameters, using empty string for missing params."""
        try:
            return template.format(**params)
        except KeyError as e:
            missing_key = str(e).strip("'")
            params_with_fallback = {**params, missing_key: ""}
            return self._safe_format(template, params_with_fallback)

    def register_translations(self, locale: str, translations: LocaleBundle) -> None:
        """Register or merge custom translations for a locale."""
        existing = self._translations.get(locale)
        if existing is not None:
            for error_type, msgs in translations.items():
                existing[error_type] = msgs
        else:
            self._translations[locale] = translations
        logger.info("Registered translations for locale '%s'", locale)

    def get_supported_locales(self) -> list[str]:
        """Get list of supported locales."""
        return [loc for loc in self._translations if loc != "zh_cn"]
