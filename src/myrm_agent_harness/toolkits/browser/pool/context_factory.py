"""Browser Context creation with emulation and domain filtering.


[INPUT]
- patchright.async_api::Browser (POS: Patchright browser instance)
- patchright.async_api::BrowserContext (POS: Patchright browser context)
- .emulation::EmulationConfig (POS: environment emulation config)
- .config::ResourceBlockConfig (POS: resource blocking config)
- domain_filter::DomainAllowlist, install_domain_filter (POS: domain filtering and resource blocking)
- .stealth::get_stealth_script (POS: stealth anti-detection JS script loader)

[OUTPUT]
- ContextFactory: context creation factory class

[POS]
Dedicated to BrowserContext creation and configuration, including:
1. Selecting launch parameters based on ContextType
2. Setting global default timeout (_DEFAULT_TIMEOUT_MS, covers all page operations)
3. Applying EmulationConfig (geolocation/timezone/locale/permissions etc.) with fallback to default_emulation
4. Installing resource blocking (image/font/media/ad-domains) independently of domain allowlist
5. Installing DomainAllowlist security filter (CSP + JS hardening + CDP audit) when allowlist provided
6. STEALTH mode injection of 13 anti-detection JS scripts (dual-layer defense: patchright CDP + JS init script)
"""

from __future__ import annotations

import contextlib
import logging
import platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Browser, BrowserContext

    from .emulation import EmulationConfig
    from .proxy import ProxyPool

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 30000  # globaldefaulttimeout, overridesall page operation(evaluate/click/goto etc.)
_STEALTH_TYPE = "stealth"  # ContextType.STEALTH.value — avoid circular import

_DEFAULT_CONTEXT_OPTIONS: dict[str, object] = {
    "viewport": {"width": 1920, "height": 1080},
    "ignore_https_errors": True,
    "extra_http_headers": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "max-age=0",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
}

_CHROME_VERSION = "147.0.0.0"

_PLATFORM_UA: dict[str, str] = {
    "Darwin": f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{_CHROME_VERSION} Safari/537.36",
    "Linux": f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{_CHROME_VERSION} Safari/537.36",
    "Windows": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{_CHROME_VERSION} Safari/537.36",
}

_STEALTH_CONTEXT_OPTIONS: dict[str, object] = {
    **_DEFAULT_CONTEXT_OPTIONS,
    "user_agent": _PLATFORM_UA.get(platform.system(), _PLATFORM_UA["Linux"]),
}


class ContextFactory:
    """Factory for creating and configuring BrowserContext instances."""

    def __init__(
        self,
        proxy_pool: ProxyPool | None = None,
        default_emulation: EmulationConfig | None = None,
    ) -> None:
        """Initialize context factory.

        Args:
            proxy_pool: Proxy pool for rotation and sticky sessions
            default_emulation: Fallback emulation config applied when caller
                does not pass an explicit ``emulation`` to ``create_context``.
                Used by BrowserPoolConfig to provide default permissions
                (e.g. clipboard-read/write) across all contexts.

        """
        self._proxy_pool = proxy_pool
        self._default_emulation = default_emulation

    async def create_context(
        self,
        browser: Browser,
        context_type: str,
        emulation: EmulationConfig | None = None,
        extra_kwargs: dict[str, object] | None = None,
        context_key: str | None = None,
    ) -> BrowserContext:
        """Create a new BrowserContext with specified configuration.

        Args:
            browser: Browser instance to create context from
            context_type: Context type (CRAWL/AGENT/STEALTH)
            emulation: Environment emulation config (geolocation/timezone/locale)
            extra_kwargs: Additional BrowserContext parameters (e.g., record_video_dir)
                Special keys (not passed to new_context):
                - domain_allowlist (DomainAllowlist): domain filtering
                - resource_block (ResourceBlockConfig): resource type blocking
            context_key: Unique context identifier for proxy sticky session binding.
                When provided, same context_key always gets the same proxy.
                Falls back to context_type if not provided.

        Returns:
            Configured BrowserContext instance with 30s default timeout

        Raises:
            Exception: If context creation or domain filter installation fails

        Note:
            All page operations (evaluate, click, goto, etc.) inherit the 30s timeout.

        """
        ctx_opts = self._build_context_options(context_type, emulation, extra_kwargs, context_key)
        domain_allowlist = extra_kwargs.get("domain_allowlist") if extra_kwargs else None
        resource_block = extra_kwargs.get("resource_block") if extra_kwargs else None

        # Try to safely extract permissions, some engines (like Firefox) don't support all Chromium permissions
        permissions = ctx_opts.get("permissions", [])
        if isinstance(permissions, list) and "clipboard-read" in permissions:
            # For Firefox/Camoufox, we might need to remove clipboard-read if it causes issues
            with contextlib.suppress(Exception):
                # We can't easily check the browser type here, but we can try/except
                pass

        try:
            context = await browser.new_context(**ctx_opts)  # type: ignore[arg-type]
        except Exception as e:
            error_str = str(e)
            if "Unknown permission" in error_str:
                # Extract the permission name from the error string (e.g. "Unknown permission: clipboard-read")
                perm = error_str.split("Unknown permission:")[-1].strip()
                logger.warning(f"Browser doesn't support {perm} permission, retrying without it")
                if "permissions" in ctx_opts and isinstance(ctx_opts["permissions"], list):
                    if perm in ctx_opts["permissions"]:
                        ctx_opts["permissions"].remove(perm)
                    # Also try removing clipboard-write if it's there, as it often fails together with clipboard-read
                    if "clipboard-write" in ctx_opts["permissions"]:
                        ctx_opts["permissions"].remove("clipboard-write")
                context = await browser.new_context(**ctx_opts)  # type: ignore[arg-type]
            else:
                raise
        context.set_default_timeout(_DEFAULT_TIMEOUT_MS)

        # Inject Progressive DomEnhancer into EVERY context
        from myrm_agent_harness.toolkits.browser.enhancers import (
            get_dom_enhancer_script,
        )

        await context.add_init_script(get_dom_enhancer_script())

        if context_type == _STEALTH_TYPE:
            await self._apply_stealth(context)

        if domain_allowlist:
            try:
                await self._install_domain_filter(context, domain_allowlist, resource_block)
            except Exception:
                await context.close()
                raise
        elif resource_block:
            try:
                await self._install_resource_blocking(context, resource_block)
            except Exception:
                await context.close()
                raise

        return context

    def _build_context_options(
        self,
        context_type: str,
        emulation: EmulationConfig | None,
        extra_kwargs: dict[str, object] | None,
        context_key: str | None = None,
    ) -> dict[str, object]:
        """Build context options based on type and configuration."""
        if context_type == _STEALTH_TYPE:
            ctx_opts = dict(_STEALTH_CONTEXT_OPTIONS)
        else:
            ctx_opts = dict(_DEFAULT_CONTEXT_OPTIONS)

        if self._proxy_pool:
            session_id = context_key or context_type
            proxy_config = self._proxy_pool.get_for_session(session_id)
            ctx_opts["proxy"] = proxy_config.to_playwright_dict()

        effective_emulation = emulation or self._default_emulation
        if effective_emulation:
            ctx_opts.update(effective_emulation.to_playwright_kwargs())

        if extra_kwargs:
            playwright_kwargs = {
                k: v for k, v in extra_kwargs.items() if k not in ("domain_allowlist", "resource_block")
            }
            ctx_opts.update(playwright_kwargs)

        return ctx_opts

    @staticmethod
    async def _apply_stealth(context: BrowserContext) -> None:
        """Apply stealth anti-detection patches to a STEALTH context.

        Injects stealth.js via add_init_script — runs before page scripts
        on every navigation within this context. Covers 13 anti-detection
        vectors including navigator patches, toString disguise, anti-debugger
        neutralization, and Performance API cleanup.
        """
        from .stealth import get_stealth_script

        await context.add_init_script(get_stealth_script())

    @staticmethod
    async def _install_domain_filter(
        context: BrowserContext,
        domain_allowlist: object,
        resource_block: object | None = None,
    ) -> None:
        """Install domain filter and resource blocking on context."""
        from myrm_agent_harness.toolkits.browser.domain_filter import (
            install_domain_filter,
        )

        await install_domain_filter(
            context,
            domain_allowlist,  # type: ignore[arg-type]
            resource_block=resource_block,  # type: ignore[arg-type]
        )

    @staticmethod
    async def _install_resource_blocking(
        context: BrowserContext,
        resource_block: object,
    ) -> None:
        """Install resource type + ad domain blocking without domain allowlist."""
        from myrm_agent_harness.toolkits.browser.domain_filter import (
            DomainAllowlist,
            install_domain_filter,
        )

        await install_domain_filter(
            context,
            DomainAllowlist(patterns=()),  # empty allowlist = no domain restriction
            resource_block=resource_block,  # type: ignore[arg-type]
        )
