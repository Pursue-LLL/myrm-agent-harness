"""Application display name and bundle identifier resolution engine.

Eliminates the anti-pattern of having models execute multiple shell exploratory commands
(e.g., mdfind, ps aux, osascript) just to resolve Chinese or colloquial app names to bundle IDs.

[INPUT]
- __future__
- code_over_prompt_types

[OUTPUT]
- AppDisplayNameResolver

[POS]
Application display name and bundle identifier resolution engine.
"""

from __future__ import annotations

from .code_over_prompt_types import AppLaunchResolverEntry


class AppDisplayNameResolver:
    """Resolves colloquial and multi-lingual application names into deterministic bundle identifiers."""

    def __init__(self) -> None:
        self._registry: dict[str, AppLaunchResolverEntry] = {}
        self._alias_index: dict[str, str] = {}
        self._register_default_profiles()

    def _register_default_profiles(self) -> None:
        """Register built-in canonical application entries."""
        defaults: list[AppLaunchResolverEntry] = [
            AppLaunchResolverEntry(
                display_name="微信",
                bundle_id="com.tencent.xinWeChat",
                executable_name="WeChat",
                aliases=("wechat", "weixin", "wx"),
            ),
            AppLaunchResolverEntry(
                display_name="剪映",
                bundle_id="com.lemon.lv",
                executable_name="JianyingPro",
                aliases=("jianying", "capcut", "capcutpro"),
            ),
            AppLaunchResolverEntry(
                display_name="飞书",
                bundle_id="com.electron.lark",
                executable_name="Lark",
                aliases=("lark", "feishu"),
            ),
            AppLaunchResolverEntry(
                display_name="钉钉",
                bundle_id="com.alibaba.DingTalkMac",
                executable_name="DingTalk",
                aliases=("dingtalk", "ding"),
            ),
            AppLaunchResolverEntry(
                display_name="Blender",
                bundle_id="org.blenderfoundation.blender",
                executable_name="Blender",
                aliases=("blender3d",),
            ),
            AppLaunchResolverEntry(
                display_name="豆包",
                bundle_id="com.bytedance.doubao.desktop",
                executable_name="Doubao",
                aliases=("doubao", "doubao_work"),
            ),
        ]
        for item in defaults:
            self.register(item)

    def register(self, entry: AppLaunchResolverEntry) -> None:
        """Register a new application descriptor into primary and alias indices."""
        key = entry.display_name.strip().lower()
        self._registry[key] = entry
        for alias in entry.aliases:
            self._alias_index[alias.strip().lower()] = key

    def resolve(self, query: str) -> AppLaunchResolverEntry | None:
        """Resolve a query string (display name or alias) into an AppLaunchResolverEntry."""
        q = query.strip().lower()
        if q in self._registry:
            return self._registry[q]
        if q in self._alias_index:
            primary_key = self._alias_index[q]
            return self._registry.get(primary_key)

        # Substring fuzzy match for partial names
        for key, entry in self._registry.items():
            if q in key or any(q in alias for alias in entry.aliases):
                return entry

        return None
