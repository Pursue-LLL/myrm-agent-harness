"""Unit tests for Slack Rotating Token Classification and Scope Inspection."""

from myrm_agent_harness.core.security.slack_rotating_token import (
    SlackScopeInspection,
    SlackScopeInspector,
    SlackTokenCategory,
    SlackTokenClassification,
    SlackTokenClassifier,
    SlackTokenType,
)


def test_strip_bearer() -> None:
    classifier = SlackTokenClassifier()

    token, is_bearer = classifier.strip_bearer("Bearer xoxb-12345")
    assert token == "xoxb-12345"
    assert is_bearer is True

    token, is_bearer = classifier.strip_bearer("bearer   xoxe.xoxp-67890  ")
    assert token == "xoxe.xoxp-67890"
    assert is_bearer is True

    token, is_bearer = classifier.strip_bearer("xoxb-plain-token")
    assert token == "xoxb-plain-token"
    assert is_bearer is False

    token, is_bearer = classifier.strip_bearer("   xoxp-spaced-token   ")
    assert token == "xoxp-spaced-token"
    assert is_bearer is False


def test_classify_rotating_tokens() -> None:
    classifier = SlackTokenClassifier()

    # 1. Rotating Bot Token
    res_bot: SlackTokenClassification = classifier.classify("xoxe.xoxb-mock-bot-token")
    assert res_bot.token_type == SlackTokenType.BOT
    assert res_bot.category == SlackTokenCategory.ROTATING
    assert res_bot.is_rotating is True
    assert res_bot.prefix_matched == "xoxe.xoxb-"
    assert res_bot.is_bearer_wrapped is False

    # 2. Rotating User Token with Bearer
    res_user: SlackTokenClassification = classifier.classify(
        "Bearer xoxe.xoxp-mock-user-token"
    )
    assert res_user.token_type == SlackTokenType.USER
    assert res_user.category == SlackTokenCategory.ROTATING
    assert res_user.is_rotating is True
    assert res_user.prefix_matched == "xoxe.xoxp-"
    assert res_user.is_bearer_wrapped is True
    assert res_user.normalized_token == "xoxe.xoxp-mock-user-token"

    # 3. Rotating Refresh Token
    res_refresh: SlackTokenClassification = classifier.classify(
        "xoxe.xoxr-mock-refresh-token"
    )
    assert res_refresh.token_type == SlackTokenType.REFRESH
    assert res_refresh.category == SlackTokenCategory.REFRESH
    assert res_refresh.is_rotating is False
    assert res_refresh.prefix_matched == "xoxe.xoxr-"

    # 4. Generic Rotating Token with Hints
    res_generic_bot: SlackTokenClassification = classifier.classify(
        "xoxe-generic-access-token", raw_token_type_hint="bot"
    )
    assert res_generic_bot.token_type == SlackTokenType.BOT
    assert res_generic_bot.category == SlackTokenCategory.ROTATING
    assert res_generic_bot.is_rotating is True
    assert res_generic_bot.prefix_matched == "xoxe"

    res_generic_user: SlackTokenClassification = classifier.classify(
        "xoxe.generic-access-token", raw_token_type_hint="user"
    )
    assert res_generic_user.token_type == SlackTokenType.USER
    assert res_generic_user.category == SlackTokenCategory.ROTATING
    assert res_generic_user.is_rotating is True

    res_generic_unknown: SlackTokenClassification = classifier.classify(
        "xoxe-unhinted-token"
    )
    assert res_generic_unknown.token_type == SlackTokenType.UNKNOWN
    assert res_generic_unknown.category == SlackTokenCategory.ROTATING
    assert res_generic_unknown.is_rotating is True


def test_classify_static_tokens() -> None:
    classifier = SlackTokenClassifier()

    # Static Bot Token
    res_b: SlackTokenClassification = classifier.classify("xoxb-static-bot-1234")
    assert res_b.token_type == SlackTokenType.BOT
    assert res_b.category == SlackTokenCategory.STATIC
    assert res_b.is_rotating is False
    assert res_b.prefix_matched == "xoxb-"

    # Static User Token
    res_u: SlackTokenClassification = classifier.classify("xoxp-static-user-5678")
    assert res_u.token_type == SlackTokenType.USER
    assert res_u.category == SlackTokenCategory.STATIC
    assert res_u.is_rotating is False
    assert res_u.prefix_matched == "xoxp-"

    # Static Refresh Token
    res_r: SlackTokenClassification = classifier.classify("xoxr-static-refresh-9012")
    assert res_r.token_type == SlackTokenType.REFRESH
    assert res_r.category == SlackTokenCategory.REFRESH
    assert res_r.is_rotating is False
    assert res_r.prefix_matched == "xoxr-"


def test_classify_fallbacks_and_unknown() -> None:
    classifier = SlackTokenClassifier()

    # Fallback to hint
    res_hint_bot: SlackTokenClassification = classifier.classify(
        "custom-token-123", raw_token_type_hint="bot"
    )
    assert res_hint_bot.token_type == SlackTokenType.BOT
    assert res_hint_bot.category == SlackTokenCategory.STATIC
    assert res_hint_bot.is_rotating is False

    res_hint_user: SlackTokenClassification = classifier.classify(
        "custom-token-456", raw_token_type_hint="user"
    )
    assert res_hint_user.token_type == SlackTokenType.USER
    assert res_hint_user.category == SlackTokenCategory.STATIC

    # Total Unknown
    res_unknown: SlackTokenClassification = classifier.classify(
        "completely-unknown-token"
    )
    assert res_unknown.token_type == SlackTokenType.UNKNOWN
    assert res_unknown.category == SlackTokenCategory.UNKNOWN
    assert res_unknown.is_rotating is False
    assert res_unknown.prefix_matched is None


def test_scope_inspector_user() -> None:
    inspector = SlackScopeInspector()

    # 1. Comma separated in authed_user.scope
    meta_user_comma: dict[str, object] = {
        "authed_user": {
            "scope": "chat:write, channels:read, users:read",
        },
        "scope": "commands",
    }
    insp1: SlackScopeInspection = inspector.inspect_scopes(
        SlackTokenType.USER, meta_user_comma
    )
    assert insp1.token_type == SlackTokenType.USER
    assert insp1.resolved_scopes == ["channels:read", "chat:write", "users:read"]
    assert insp1.source_field == "authed_user.scope"

    # 2. List in authed_user.scope
    meta_user_list: dict[str, object] = {
        "authed_user": {
            "scope": ["chat:write", "files:read"],
        }
    }
    insp2: SlackScopeInspection = inspector.inspect_scopes(
        SlackTokenType.USER, meta_user_list
    )
    assert insp2.resolved_scopes == ["chat:write", "files:read"]
    assert insp2.source_field == "authed_user.scope"

    # 3. Fallback to top-level scope if authed_user missing
    meta_user_fallback: dict[str, object] = {
        "scope": "identify, incoming-webhook",
    }
    insp3: SlackScopeInspection = inspector.inspect_scopes(
        SlackTokenType.USER, meta_user_fallback
    )
    assert insp3.resolved_scopes == ["identify", "incoming-webhook"]
    assert insp3.source_field == "scope"


def test_scope_inspector_bot() -> None:
    inspector = SlackScopeInspector()

    # 1. Top-level space separated scope
    meta_bot: dict[str, object] = {
        "scope": "app_mentions:read chat:write commands",
        "authed_user": {
            "scope": "identify",
        },
    }
    insp_bot: SlackScopeInspection = inspector.inspect_scopes(
        SlackTokenType.BOT, meta_bot
    )
    assert insp_bot.token_type == SlackTokenType.BOT
    assert insp_bot.resolved_scopes == ["app_mentions:read", "chat:write", "commands"]
    assert insp_bot.source_field == "scope"

    # 2. Fallback to authed_user if scope is missing
    meta_bot_fallback: dict[str, object] = {
        "authed_user": {
            "scope": "channels:history",
        }
    }
    insp_bot_fb: SlackScopeInspection = inspector.inspect_scopes(
        SlackTokenType.BOT, meta_bot_fallback
    )
    assert insp_bot_fb.resolved_scopes == ["channels:history"]
    assert insp_bot_fb.source_field == "authed_user.scope"

    # 3. Empty metadata
    insp_empty: SlackScopeInspection = inspector.inspect_scopes(SlackTokenType.BOT, {})
    assert insp_empty.resolved_scopes == []
    assert insp_empty.source_field == "none"
