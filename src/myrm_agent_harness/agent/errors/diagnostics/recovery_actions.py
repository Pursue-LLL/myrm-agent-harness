"""Recovery action buttons for LLM error diagnostics.

[INPUT]
- diagnostics.i18n::get_locale_manager (POS: Framework-level i18n for LLM error diagnostics)

[OUTPUT]
- build_recovery_actions: Localized {id, label, url} buttons for a diagnostic error type

[POS]
Recovery action catalogue of the diagnostics engine. Only error types with a clear, single-click
fix (invalid key, empty balance, unknown model) map to buttons; every other error type has none.
"""

from myrm_agent_harness.agent.errors.diagnostics.i18n import get_locale_manager

_ACTION_DEFS: dict[str, list[tuple[str, str]]] = {
    "api_key": [("update_key", "/settings")],
    "billing": [("top_up", "/settings")],
    "model": [("change_model", "/settings")],
    "custom_model_not_found": [("change_model", "/settings")],
}

_LABELS: dict[str, str] = {
    "update_key": "Update API Key",
    "top_up": "Top Up Balance",
    "change_model": "Change Model",
}

_LABELS_I18N: dict[str, dict[str, str]] = {
    "zh-CN": {"update_key": "更新 API 密钥", "top_up": "充值余额", "change_model": "切换模型"},
    "ja": {"update_key": "APIキーを更新", "top_up": "残高をチャージ", "change_model": "モデルを変更"},
    "ko": {"update_key": "API 키 업데이트", "top_up": "잔액 충전", "change_model": "모델 변경"},
    "de": {
        "update_key": "API-Schlüssel aktualisieren",
        "top_up": "Guthaben aufladen",
        "change_model": "Modell wechseln",
    },
}


def build_recovery_actions(error_type: str, locale: str | None = "en") -> list[dict[str, str]]:
    """Return localized actionable recovery buttons for the given error type.

    Each action is a dict with {id, label, url} matching the frontend RecoveryAction type.
    Only error types with clear, single-click resolutions produce actions.
    ``None`` locale falls back to framework auto-detection (mirrors ``LLMErrorDiagnostic.diagnose``).
    """
    if not locale:
        locale = get_locale_manager().detect_locale()

    defs = _ACTION_DEFS.get(error_type)
    if not defs:
        return []

    locale_labels = _LABELS_I18N.get(locale, {})
    if not locale_labels:
        lang = locale.split("-")[0].split("_")[0]
        for key in _LABELS_I18N:
            if key.split("-")[0] == lang:
                locale_labels = _LABELS_I18N[key]
                break

    return [
        {
            "id": action_id,
            "label": locale_labels.get(action_id, _LABELS[action_id]),
            "url": url,
        }
        for action_id, url in defs
    ]
