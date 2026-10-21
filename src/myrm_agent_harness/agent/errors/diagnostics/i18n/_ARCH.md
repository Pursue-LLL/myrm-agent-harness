# i18n/

## Overview
Framework-level i18n for LLM error diagnostics. Bundled JSON locales (en/zh-CN/ja/ko/de); override via `MYRM_LOCALES_DIR`. Business layers may extend via `register_translations()`.

## File & Submodule Index

| File / Dir | Role | Description | I/O/P |
|------------|------|-------------|-------|
| __init__.py | Package | Re-exports LocaleManager and get_locale_manager singleton | ✅ |
| constants.py | Config | REQUIRED_ERROR_TYPES for completeness validation | ✅ |
| manager.py | Core | LocaleManager — detection, bundled JSON load, formatting | ✅ |
| locales/ | Data | Bundled flat JSON locale files shipped with the wheel | — |
| locales/en.json | Data | English diagnostic strings | — |
| locales/zh-CN.json | Data | Simplified Chinese diagnostic strings | — |
| locales/ja.json | Data | Japanese diagnostic strings | — |
| locales/ko.json | Data | Korean diagnostic strings | — |
| locales/de.json | Data | German diagnostic strings | — |

## Module Dependencies

- No dependency on `myrm-agent-server`; locales are self-contained in `locales/`
