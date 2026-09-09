"""Common Android Application Aliases and Package Mappings.

[INPUT]
- Semantic app name or alias string

[OUTPUT]
- Canonical Android package name (or the original string if not aliased)

[POS]
myrm_agent_harness.toolkits.mobile_adb.app_aliases
"""

from __future__ import annotations

# Common app package mappings for seamless semantic launch
COMMON_APP_ALIASES: dict[str, str] = {
    "wechat": "com.tencent.mm",
    "weixin": "com.tencent.mm",
    "微信": "com.tencent.mm",
    "qq": "com.tencent.mobileqq",
    "feishu": "com.ss.android.lark",
    "lark": "com.ss.android.lark",
    "飞书": "com.ss.android.lark",
    "dingtalk": "com.alibaba.android.rimet",
    "钉钉": "com.alibaba.android.rimet",
    "settings": "com.android.settings",
    "设置": "com.android.settings",
    "chrome": "com.android.chrome",
    "browser": "com.android.browser",
    "camera": "com.android.camera",
    "相机": "com.android.camera",
    "gallery": "com.android.gallery3d",
    "相册": "com.android.gallery3d",
}


def resolve_package_alias(name_or_alias: str) -> str:
    """Resolve a semantic app name (e.g. 'wechat', 'settings') to its Android package name."""
    cleaned = name_or_alias.strip().lower()
    return COMMON_APP_ALIASES.get(cleaned, name_or_alias.strip())
