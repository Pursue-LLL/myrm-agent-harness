"""Internationalization support for error diagnostics.

[INPUT]

[OUTPUT]
- Localized error messages and resolution steps

[POS]
Framework-level i18n for LLM error diagnostics, supporting en/zh-CN/ja/ko/de
"""

from .manager import LocaleManager

# Global singleton instance
_locale_manager = LocaleManager()


def get_locale_manager() -> LocaleManager:
    """Get the global LocaleManager instance."""
    return _locale_manager


__all__ = ["LocaleManager", "get_locale_manager"]
