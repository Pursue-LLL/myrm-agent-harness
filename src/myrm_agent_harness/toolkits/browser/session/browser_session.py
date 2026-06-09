"""Browser session — aggregation root with SOLID principles.


[INPUT]
- pool.browser_pool::GlobalBrowserPool (POS: global browser pool)
- session.tab_controller::TabController (POS: tab lifecycle management)
- navigation::Navigator (POS: page navigation with throttling)
- session.snapshot_manager::SnapshotManager (POS: snapshot generation)
- session.interactor::Interactor (POS: element interaction + ref failure diagnosis and monitoring)
- session.extractor::Extractor (POS: content extraction)
- session.structured_extractor::StructuredExtractor (POS: LLM-based structured data extraction using JSON Schema)
- session.vision_verifier::VisionVerifier (POS: 3-layer visual action verification)
- session.network_logger::NetworkLogger (POS: network request log capture)
- session.network_intelligence::NetworkIntelligence (POS: CDP-based lazy API response body retrieval)
- session_vault::SessionVault (POS: AES-256-GCM encrypted session storage)
- snapshot::RefInfo (POS: element reference metadata)
- domain_filter::DomainAllowlist (POS: domain filter allowlist)
- observability::BrowserObservability (POS: recording and profiling)
- session.browser_session_page_mixin::BrowserSessionPageMixin (POS: viewport/dialog/JS and other page-level APIs)
- session.browser_session_persistence_mixin::BrowserSessionPersistenceMixin (POS: SessionVault persistence API)
- session.browser_session_recording_mixin::BrowserSessionRecordingMixin (POS: trace/HAR recording API)
- session.download_manager::DownloadManager, DownloadConfig (POS: file download management)
- session.dialog_manager::DialogManager, DialogPolicy (POS: JS dialog lifecycle management)

[OUTPUT]
- BrowserSession: browser session manager (aggregate root)
  - snapshot(...) -> SnapshotResult: generate ARIA snapshot (frozen dataclass, immutable)
  - extract_text(...) -> str: extract page text with pagination support
  - extract_structured(...) -> str: extract structured JSON data via LLM + JSON Schema
  - get_ref_info(ref_id: str) -> RefInfo | None: get element reference info
  - get_all_refs() -> MappingProxyType[str, RefInfo]: get all element reference mappings (immutable view)
  - get_session_hash(domain: str) -> str | None: get cached session state hash (in-memory read)
  - stats: dict[str, object]: statistics info (includes ref_failures monitoring metrics)

[POS]
Browser session manager. As the aggregate root, composes single-responsibility components:
1. TabController (tab management)
2. Navigator (navigation with throttling)
3. SnapshotManager (snapshots)
4. Interactor (interaction + failure diagnosis and monitoring)
5. Extractor (raw content extraction)
6. StructuredExtractor (LLM-based structured data extraction, optional)
7. VisionVerifier (visual action verification, optional)
8. NetworkLogger (network request logging)
9. NetworkIntelligence (CDP-based lazy API response body retrieval)
10. SessionVault (encrypted session storage, optional)
11. DownloadManager (file download management, optional)
12. CaptchaCoordinator (CAPTCHA detection and solving coordination, optional)
13. DialogManager (JS dialog lifecycle handling with configurable policy)

The aggregate root class combines three Mixins (Persistence/Recording/Page) via multiple inheritance, coordinating with Tab/navigation/snapshot/interaction/extraction submodules.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from myrm_agent_harness.toolkits.browser.diff import ComparisonResult
from myrm_agent_harness.toolkits.browser.observability import BrowserObservability
from myrm_agent_harness.toolkits.browser.recording_manager import RecordingManager
from myrm_agent_harness.toolkits.browser.utils.selectors import PASSWORD_FIELD_SELECTOR

from ..navigation import Navigator
from .browser_session_page_mixin import BrowserSessionPageMixin
from .browser_session_persistence_mixin import BrowserSessionPersistenceMixin
from .browser_session_recording_mixin import BrowserSessionRecordingMixin
from .console_logger import ConsoleLogger
from .dialog_manager import DialogManager, DialogPolicy
from .download_manager import DownloadConfig, DownloadManager, DownloadResult
from .extractor import Extractor
from .interactor import Interactor
from .network_logger import NetworkLogger
from .network_intelligence import NetworkIntelligence
from .page_analyzer import PageAnalyzer
from .session_persistence import SessionPersistence
from .snapshot_manager import SnapshotManager, SnapshotResult
from .tab_controller import TabController
from .vision_verifier import VisionVerifier
from .structured_extractor import StructuredExtractor

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.toolkits.browser.captcha.protocols import CaptchaSolver
    from myrm_agent_harness.toolkits.browser.domain_filter import DomainAllowlist
    from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
    from myrm_agent_harness.toolkits.browser.session_vault import SessionVault
    from myrm_agent_harness.toolkits.browser.snapshot import RefInfo

logger = logging.getLogger(__name__)


@runtime_checkable
class ContentVault(Protocol):
    """Minimal vault interface for persisting large extracted content."""

    def put(self, content: str | bytes, filename: str, content_type: str | None = None, description: str = "") -> str:
        """Store content and return a URI pointer (e.g. ``vault://<uuid>``)."""
        ...


class BrowserSession(
    BrowserSessionPersistenceMixin,
    BrowserSessionRecordingMixin,
    BrowserSessionPageMixin,
):
    """Browser session manager (aggregate root)

    组合 TabController、Navigator、SnapshotManager、Interactor、Extractor、NetworkLogger、SessionPersistence,
    Provides a unified browser automation API. Follows SOLID, each component has a single responsibility。
    """

    def __init__(
        self,
        browser_pool: GlobalBrowserPool,
        context_type: ContextType,
        context_key: str | None = None,
        session_vault: SessionVault | None = None,
        observability: BrowserObservability | None = None,
        debug_mode: bool = False,
        domain_allowlist: DomainAllowlist | None = None,
        download_config: DownloadConfig | None = None,
        auto_restore_domains: list[str] | None = None,
        captcha_solver: CaptchaSolver | None = None,
        content_vault: ContentVault | None = None,
        vision_llm: BaseChatModel | None = None,
        *,
        allow_private_networks: bool = False,
        engine_preference: str | None = None,
        launch_mode_preference: str | None = None,
        dialog_policy: str | None = None,
    ):
        """Initialize BrowserSession.

        Args:
            browser_pool: Global browser pool
            context_type: Context purpose classification
            context_key: Context identifier
            session_vault: Session vault for persistence
            observability: Observability configuration
            debug_mode: Enable debug mode
            domain_allowlist: Domain allowlist
            download_config: Download configuration
            auto_restore_domains: Domains to auto-restore session for
            captcha_solver: CAPTCHA solver
            content_vault: Content vault for storing downloads/screenshots
            vision_llm: Vision LLM for visual tasks
            allow_private_networks: Allow navigation to private networks
            engine_preference: Preferred browser engine (e.g. 'chromium_patchright', 'firefox_camoufox').
            launch_mode_preference: Per-agent launch mode override (e.g. 'extension' to use user's real browser).
            dialog_policy: Dialog handling strategy ('smart', 'auto_accept', 'auto_dismiss', 'wait_for_agent').
        """
        from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine, LaunchMode

        try:
            self._engine_preference = BrowserEngine(engine_preference) if engine_preference else None
        except ValueError:
            logger.warning(f"Invalid engine preference '{engine_preference}', falling back to pool default.")
            self._engine_preference = None

        try:
            self._launch_mode_preference = LaunchMode(launch_mode_preference) if launch_mode_preference else None
        except ValueError:
            logger.warning(f"Invalid launch_mode preference '{launch_mode_preference}', falling back to pool default.")
            self._launch_mode_preference = None

        self._browser_pool = browser_pool
        self._context_type = context_type
        self._context_key = context_key
        self._observability = observability
        self._debug_mode = debug_mode
        self._allow_private_networks = allow_private_networks
        self._auto_restore_domains = auto_restore_domains or []
        self._auto_restored = False

        context_kwargs: dict[str, object] = {}
        if observability:
            context_kwargs.update(observability.get_context_kwargs())
        if domain_allowlist:
            context_kwargs["domain_allowlist"] = domain_allowlist
        if download_config is not None:
            context_kwargs["accept_downloads"] = True
        self._tab_controller = TabController(browser_pool, context_type, context_kwargs if context_kwargs else None)
        self._navigator: Navigator | None = None
        self._snapshot_manager: SnapshotManager | None = None
        self._interactor: Interactor | None = None
        self._extractor: Extractor | None = None
        self._network_logger = NetworkLogger()
        self._network_intelligence = NetworkIntelligence()
        self._console_logger = ConsoleLogger()
        self._persistence: SessionPersistence | None = SessionPersistence(session_vault) if session_vault else None
        self._recording_manager: RecordingManager | None = None
        self._download_manager: DownloadManager | None = (
            DownloadManager(download_config) if download_config is not None else None
        )
        self._session_hash_cache: dict[str, str] = {}
        self._content_vault = content_vault
        self._vision_verifier = VisionVerifier(vision_llm)
        self._structured_extractor = StructuredExtractor(vision_llm)

        self._session_lifecycle_hook = None

        # CAPTCHA coordination (optional — only active when a solver is provided)
        if captcha_solver is not None:
            from myrm_agent_harness.toolkits.browser.captcha import CaptchaCoordinator

            self._captcha_coordinator: CaptchaCoordinator | None = CaptchaCoordinator(captcha_solver)
        else:
            self._captcha_coordinator = None

        # Dialog handling (always active — default SMART policy)
        try:
            policy = DialogPolicy(dialog_policy) if dialog_policy else DialogPolicy.SMART
        except ValueError:
            logger.warning(f"Invalid dialog_policy '{dialog_policy}', falling back to SMART.")
            policy = DialogPolicy.SMART
        self._dialog_manager = DialogManager(policy=policy)

    async def new_tab(self, url: str | None = None) -> str:
        """Create new Tab or reuse existing same-origin Tab, return Tab ID."""
        if url:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"

            existing = self._tab_controller.find_tab_by_origin(origin)
            if existing is not None:
                await self._tab_controller.switch_tab(existing.tab_id)
                await self._initialize_components()
                await self.navigate(url)
                return existing.tab_id

        tab_id = await self._tab_controller.create_tab(
            self._context_key,
            engine_preference=self._engine_preference,
            launch_mode_preference=self._launch_mode_preference,
        )
        await self._initialize_components()

        if url:
            await self.navigate(url)

        return tab_id

    async def navigate(self, url: str, verify_goal: str | None = None) -> str:
        """Navigate to URL (auto-injects site experience, auto-detects CAPTCHA)."""
        await self._ensure_components()

        from myrm_agent_harness.toolkits.browser.utils.proxy_error import is_blocked_response, is_proxy_error

        max_attempts = 3
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            navigator = self._require_navigator()
            snapshot_manager = self._require_snapshot_manager()
            page = self._tab_controller.get_active_page()

            baseline_screenshot = None
            if verify_goal:
                try:
                    from myrm_agent_harness.toolkits.browser.utils.selectors import PASSWORD_FIELD_SELECTOR

                    password_locator = page.locator(PASSWORD_FIELD_SELECTOR)
                    baseline_screenshot = await page.screenshot(type="png", full_page=False, mask=[password_locator])
                except Exception as e:
                    logger.warning("Failed to take baseline screenshot for navigation verification: %s", e)

            try:
                title, final_url, status_code = await navigator.goto(url)

                if is_blocked_response(status_code):
                    raise Exception(f"Blocked response detected: HTTP {status_code}")

                break  # Success, exit retry loop

            except Exception as e:
                if (is_proxy_error(e) or "Blocked response" in str(e)) and attempt < max_attempts:
                    logger.warning(
                        f"Proxy error or block detected during navigation to {url}: {e}. "
                        f"Quarantining proxy and retrying (attempt {attempt}/{max_attempts})..."
                    )

                    if self._context_key and self._browser_pool._proxy_pool:
                        # Quarantine the bad proxy and release the sticky session
                        # We use duck typing/hasattr in case it's not RoundRobinProxyPool
                        if hasattr(self._browser_pool._proxy_pool, "report_failure"):
                            self._browser_pool._proxy_pool.report_failure(self._context_key)
                        else:
                            self._browser_pool._proxy_pool.release_session(self._context_key)

                    # Restart session to get a new proxy and migrate state losslessly
                    await self.restart(restore_url=False)
                    continue

                # If not a proxy error or out of retries, re-raise
                raise

        # CAPTCHA detection: inspect the loaded page for blocking CAPTCHAs
        captcha_result_msg: str | None = None
        if self._captcha_coordinator is not None:
            captcha_result_msg = await self._handle_captcha_if_detected()
            if captcha_result_msg:
                # Auto-fallback to CAMOUFOX if Chromium is blocked and CAPTCHA is not resolved
                if "not resolved" in captcha_result_msg:
                    from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine

                    current_engine = self._engine_preference or BrowserEngine.CHROMIUM_PATCHRIGHT
                    if current_engine != BrowserEngine.FIREFOX_CAMOUFOX:
                        logger.warning(
                            f"CAPTCHA not resolved with {current_engine.value}. Auto-upgrading to CAMOUFOX and retrying..."
                        )
                        await self.notify_progress(
                            "Detected advanced anti-bot protection. Upgrading browser engine to stealth mode..."
                        )
                        await self.restart(engine=BrowserEngine.FIREFOX_CAMOUFOX.value, restore_url=False)
                        # Re-acquire components after restart
                        navigator = self._require_navigator()
                        snapshot_manager = self._require_snapshot_manager()
                        page = self._tab_controller.get_active_page()
                        # Retry navigation
                        title, final_url, status_code = await navigator.goto(url)
                        # Check CAPTCHA again after retry
                        captcha_result_msg = await self._handle_captcha_if_detected()
                        if captcha_result_msg:
                            title = await self._tab_controller.get_active_page().title()
                            final_url = self._tab_controller.get_active_page().url
                else:
                    title = await self._tab_controller.get_active_page().title()
                    final_url = self._tab_controller.get_active_page().url

        snapshot_manager.reset_diff_baseline()
        self._tab_controller.clear_text_snapshot()

        result = f"Navigated to {final_url} (status={status_code}, title={title})"
        if captcha_result_msg:
            result = f"{result}\n{captcha_result_msg}"

        experience_hint = self._get_site_experience_hint(final_url)
        if experience_hint:
            result = f"{result}\n{experience_hint}"

        if verify_goal and baseline_screenshot:
            await self.notify_progress(f"Verifying navigation goal: '{verify_goal}'...")
            _success, verify_msg = await self._vision_verifier.verify_action(
                page=page,
                baseline_screenshot=baseline_screenshot,
                verify_goal=verify_goal,
            )
            result = f"{result}\n\n{verify_msg}"

        return result

    async def _handle_captcha_if_detected(self) -> str | None:
        """Detect and handle blocking CAPTCHAs on the current page.

        Called after navigate() and after click/dblclick interactions.

        Returns:
            A status message if a CAPTCHA was detected and handled, otherwise None.
        """
        if self._captcha_coordinator is None:
            return None

        from myrm_agent_harness.toolkits.browser.captcha import detect_captcha

        page = self._tab_controller.get_active_page()
        captcha_info = await detect_captcha(page)

        if captcha_info is None or not captcha_info.blocking:
            return None

        solve_result = await self._captcha_coordinator.handle_captcha(captcha_info, page)
        self._captcha_coordinator.reset()

        if solve_result.success:
            return f"CAPTCHA resolved ({captcha_info.captcha_type.value}) via {solve_result.method}"
        return f"CAPTCHA not resolved ({captcha_info.reason}): {solve_result.message}"

    async def snapshot(
        self,
        scope: str = "content",
        compact: bool = False,
        selector: str = "",
        max_tokens: int = 0,
        diff: bool = True,
        cursor_interactive: bool = True,
        include_iframes: bool = True,
        max_depth: int | None = None,
        include_bbox: bool = False,
    ) -> SnapshotResult:
        """Generate ARIA snapshot (with iframe traversal)"""
        await self._ensure_components()
        snapshot_manager = self._require_snapshot_manager()
        interactor = self._require_interactor()

        if self._debug_mode:
            include_bbox = True

        result: SnapshotResult = await snapshot_manager.get_snapshot(
            scope=scope,
            compact=compact,
            selector=selector,
            max_tokens=max_tokens,
            diff=diff,
            cursor_interactive=cursor_interactive,
            include_iframes=include_iframes,
            max_depth=max_depth,
            include_bbox=include_bbox,
        )

        page = self._tab_controller.get_active_page()
        tab_id = self._tab_controller.get_active_tab_id()
        current_url = page.url

        self._tab_controller.update_snapshot_url(tab_id, current_url)
        interactor.update_refs(result.refs, last_snapshot_url=current_url)

        return result

    async def inspect(self) -> str:
        """Quick page structure analysis (metadata, smaller output than full snapshot)"""
        await self._ensure_components()

        page = self._tab_controller.get_active_page()
        analyzer = PageAnalyzer(page)
        structure = await analyzer.analyze()
        return analyzer.format_report(structure)

    def get_ref_info(self, ref_id: str) -> RefInfo | None:
        """Get RefInfo for a given ref_id."""
        if self._interactor is None:
            return None
        return self._interactor._refs.get(ref_id)

    def get_all_refs(self) -> MappingProxyType[str, RefInfo]:
        """Get all RefInfo mappings from last snapshot."""
        if self._interactor is None:
            return MappingProxyType({})
        return MappingProxyType(self._interactor._refs)

    def get_session_hash(self, domain: str) -> str | None:
        """Get cached session hash for a domain.

        Args:
            domain: Session domain

        Returns:
            SHA-256 hash of session state, or None if not cached
        """
        return self._session_hash_cache.get(domain)

    async def interact(self, action: str, ref: str, text: str = "", verify_goal: str | None = None) -> str:
        """Element interaction (13 operation types) with optional visual verification."""
        await self._ensure_components()
        interactor = self._require_interactor()
        page = self._tab_controller.get_active_page()

        baseline_screenshot = None
        if verify_goal:
            try:
                from myrm_agent_harness.toolkits.browser.utils.selectors import PASSWORD_FIELD_SELECTOR

                password_locator = page.locator(PASSWORD_FIELD_SELECTOR)
                baseline_screenshot = await page.screenshot(type="png", full_page=False, mask=[password_locator])
            except Exception as e:
                logger.warning("Failed to take baseline screenshot for verification: %s", e)

        result = await interactor.interact(action, ref, text)
        self._tab_controller.clear_text_snapshot()

        if action in ("click", "dblclick") and self._captcha_coordinator is not None:
            captcha_msg = await self._handle_captcha_if_detected()
            if captcha_msg:
                result = f"{result}\n{captcha_msg}"

        if verify_goal and baseline_screenshot:
            await self.notify_progress(f"Verifying action goal: '{verify_goal}'...")
            _success, verify_msg = await self._vision_verifier.verify_action(
                page=page,
                baseline_screenshot=baseline_screenshot,
                verify_goal=verify_goal,
            )
            result = f"{result}\n\n{verify_msg}"
            # We append the failure to the result so the LLM can reflect on it.
            # The tool call itself doesn't raise an exception, it just reports the failure.

        return result

    async def extract_text(self, resume_cursor: int = 0, max_length: int = 20000, selector: str = "") -> str:
        """Extract page text."""
        await self._ensure_components()
        extractor = self._require_extractor()
        tab_id = self._tab_controller.get_active_tab_id()

        import hashlib

        current_hash = hashlib.md5(f"{selector}".encode()).hexdigest()

        snapshot_data = self._tab_controller.get_text_snapshot(tab_id)
        if resume_cursor > 0 and snapshot_data is not None and snapshot_data[1] == current_hash:
            full_text = snapshot_data[0]
        else:
            full_text = await extractor.extract_full_text(selector=selector)
            self._tab_controller.set_text_snapshot(tab_id, full_text, current_hash)

        chunk = full_text[resume_cursor : resume_cursor + max_length]
        total_len = len(full_text)

        if resume_cursor + max_length < total_len:
            next_cursor = resume_cursor + max_length
            if total_len > 100000 and resume_cursor == 0 and self._content_vault is not None:
                try:
                    page = self._tab_controller.get_active_page()
                    url = page.url
                    vault_uri = self._content_vault.put(
                        content=full_text,
                        filename="Extracted_Web_Content.md",
                        description=f"Extracted from {url} with selector '{selector}'",
                    )
                    logger.warning("BrowserSession: Extracted content extremely long, saved to vault: %s", vault_uri)
                    return f"[System Note: WebpageContent极长 ({total_len} Characters)， is 了节省您  Context Window， already 整体固化至沙箱工件库。]\n\n工件Link: {vault_uri}\n\n or less 是前 {max_length} Characters预览：\n{chunk}"
                except Exception as e:
                    logger.warning("Failed to save to Vault: %s", e)

            chunk += f"\n\n[System Note: Text is extremely long and truncated at {next_cursor} chars. {total_len - next_cursor} chars remaining. Please call extract_text again with resume_cursor={next_cursor} to get the next page.]"

        return chunk

    async def extract_structured(
        self,
        schema_json: str,
        selector: str = "",
        already_collected_json: str = "",
    ) -> str:
        """Extract structured data from page text using LLM + JSON Schema.

        Args:
            schema_json: JSON Schema string defining desired output structure.
            selector: CSS selector to target specific page elements.
            already_collected_json: JSON array of previously collected items to skip duplicates.

        Returns:
            JSON string conforming to schema, or error message.
        """
        import json as json_mod

        if not self._structured_extractor.enabled:
            return "[Error] Structured extraction unavailable: no vision_llm configured for this session."

        await self._ensure_components()
        extractor = self._require_extractor()

        # Parse schema
        try:
            schema = json_mod.loads(schema_json)
        except json_mod.JSONDecodeError as e:
            return f"[Error] Invalid JSON Schema: {e}"

        # Parse already_collected
        already_collected: list[dict] | None = None
        if already_collected_json:
            try:
                already_collected = json_mod.loads(already_collected_json)
                if not isinstance(already_collected, list):
                    already_collected = None
            except json_mod.JSONDecodeError:
                pass

        # Extract raw text from page (full text, no truncation for structured extraction)
        full_text = await extractor.extract_full_text(selector=selector)

        if not full_text.strip():
            return "[Error] No text content found on page (selector may be too restrictive)."

        return await self._structured_extractor.extract(
            text=full_text,
            schema=schema,
            already_collected=already_collected,
        )

    async def extract_screenshot(self, scale: float = 1.0) -> str:
        """ExtractScreenshot(Base64 JPEG)"""
        await self._ensure_components()
        extractor = self._require_extractor()

        retina = scale >= 2.0
        return await extractor.extract_screenshot(retina)

    async def compare_screenshots(
        self,
        baseline: str,
        strategy: Literal["fast", "accurate", "auto"] = "auto",
        similarity_threshold: float = 0.9,
        color_tolerance: float = 0.1,
        mismatch_threshold: float = 5.0,
        include_aa: bool = True,
    ) -> ComparisonResult:
        """对比CurrentScreenshot and 基准Screenshot"""
        await self._ensure_components()
        extractor = self._require_extractor()
        return await extractor.compare_screenshots(
            baseline,
            strategy,
            similarity_threshold=similarity_threshold,
            color_tolerance=color_tolerance,
            mismatch_threshold=mismatch_threshold,
            include_aa=include_aa,
        )

    async def compare_screenshot(self) -> str:
        """对比Current and 上次Screenshot"""
        await self._ensure_components()
        extractor = self._require_extractor()

        return await extractor.compare_screenshot()

    async def export_pdf(self, path: str) -> str:
        """Export PDF  to 指定Path"""
        await self._ensure_components()
        extractor = self._require_extractor()

        return await extractor.export_pdf(path)

    async def download_url(self, url: str, timeout: float | None = None) -> DownloadResult | None:
        """Download a file from a URL.

        Args:
            url: URL to download
            timeout: Timeout in seconds (defaults to config)

        Returns:
            DownloadResult if successful, None otherwise
        """
        if self._download_manager is None:
            raise RuntimeError("Download support not enabled. Pass download_config to BrowserSession.")
        await self._ensure_components()
        page = self._tab_controller.get_active_page()
        return await self._download_manager.download_url(page, url, timeout)

    async def check_and_download_pdf(self) -> DownloadResult | None:
        """Check if current page is a PDF and auto-download it."""
        if self._download_manager is None:
            return None
        await self._ensure_components()
        page = self._tab_controller.get_active_page()
        return await self._download_manager.check_and_download_pdf(page)

    def list_downloads(self) -> list[DownloadResult]:
        """Get all download results."""
        if self._download_manager is None:
            return []
        return self._download_manager.downloads

    @property
    def last_download(self) -> DownloadResult | None:
        """Get the most recent download result, or None."""
        if self._download_manager is None:
            return None
        return self._download_manager.last_download

    @property
    def download_enabled(self) -> bool:
        """Whether download support is configured."""
        return self._download_manager is not None

    def list_tabs(self) -> list[str]:
        """List all Tabs ID"""
        return self._tab_controller.list_tabs()

    def list_tabs_with_info(self) -> list[dict[str, str]]:
        """List all tabs with domain info for display."""
        return self._tab_controller.list_tabs_with_info()

    def get_active_tab_id(self) -> str:
        """GetCurrent活跃 Tab ID"""
        return self._tab_controller.get_active_tab_id()

    async def close_tab(self, tab_id: str) -> str:
        """Close specified Tab; if still has Tab, bind Component to Current active page."""
        if self._tab_controller.list_tabs() and tab_id == self._tab_controller.get_active_tab_id():
            try:
                page = self._tab_controller.get_active_page()
                self._network_logger.detach_page(page)
                self._console_logger.detach_page(page)
                self._dialog_manager.detach(page)
            except RuntimeError:
                pass
        await self._tab_controller.close_tab(tab_id)
        if self._tab_controller.list_tabs():
            await self._initialize_components()
        else:
            self._navigator = None
            self._snapshot_manager = None
            self._interactor = None
            self._extractor = None
            self._network_logger.stop_capture()
            self._console_logger.stop_capture()
            await self._network_intelligence.detach()
        return f"Closed tab {tab_id}"

    async def switch_tab(self, tab_id: str) -> str:
        """Switch active Tab and rebind Navigator / Snapshot / Interactor / Extract etc. Component."""
        await self._tab_controller.switch_tab(tab_id)
        await self._initialize_components()
        return f"Switched to tab {tab_id}"

    def get_console_log(self) -> str:
        """Get captured browser console messages (errors, warnings, logs)."""
        return self._console_logger.get_summary()

    def get_network_log(self, filter_mode: str = "api") -> str:
        """Get network request logs."""
        api_summary = self._network_intelligence.get_summary()

        if api_summary and filter_mode == "api":
            parts = [
                "API Requests (use network_detail with index to view response body):",
                api_summary,
            ]
            failed_summary = self._network_logger.get_summary("failed")
            if "No network requests" not in failed_summary:
                parts.append(f"\n{failed_summary}")
            return "\n".join(parts)

        summary = self._network_logger.get_summary(filter_mode)
        if api_summary:
            summary += (
                "\n\nAPI Requests (use network_detail with index to view response body):"
                f"\n{api_summary}"
            )
        return summary

    async def get_network_detail(self, index: int) -> str:
        """Get response body for a tracked API request by index."""
        return await self._network_intelligence.get_response_body(index)

    async def replay_network_request(self, index: int) -> str:
        """Replay a tracked API request using page.evaluate(fetch(...))."""
        api_requests = self._network_intelligence.get_api_requests()
        if index < 1 or index > len(api_requests):
            return f"Error: Invalid index {index}. Valid range: 1-{len(api_requests)}"

        record = api_requests[index - 1]

        await self._ensure_components()
        page = self._tab_controller.get_active_page()

        url_js = json.dumps(record.url)
        method_js = json.dumps(record.method)

        fetch_opts_parts = [f'"method": {method_js}']
        if record.post_data and record.method in ("POST", "PUT", "PATCH"):
            body_js = json.dumps(record.post_data)
            fetch_opts_parts.append(f'"body": {body_js}')
            fetch_opts_parts.append('"headers": {"Content-Type": "application/json"}')

        fetch_opts = "{" + ", ".join(fetch_opts_parts) + "}"

        js_code = f"""
            async () => {{
                const resp = await fetch({url_js}, {fetch_opts});
                const text = await resp.text();
                return text.substring(0, 8000);
            }}
        """

        try:
            result = await page.evaluate(js_code)
            return str(result) if result else "Empty response"
        except Exception as exc:
            return f"Error replaying request: {exc}"

    async def notify_progress(self, message: str) -> None:
        """Send进度通知"""
        if self._observability:
            await self._observability.notify_progress(message)

    async def get_final_screenshot(self) -> bytes:
        """GetfinalStateScreenshot"""
        await self._ensure_components()

        if not self._tab_controller.list_tabs():
            raise RuntimeError("Cannot capture screenshot: no active tabs")

        page = self._tab_controller.get_active_page()
        # Redact password fields in screenshot to prevent privacy leaks
        password_locator = page.locator(PASSWORD_FIELD_SELECTOR)
        return await page.screenshot(type="png", full_page=False, mask=[password_locator])

    def mark_task_success(self) -> None:
        """标记任务ExecuteSuccess"""
        if self._observability:
            self._observability.mark_task_status(success=True)

    def mark_task_failure(self) -> None:
        """标记任务ExecuteFailure"""
        if self._observability:
            self._observability.mark_task_status(success=False)

    async def restart(self, engine: str | None = None, restore_url: bool = True) -> str:
        """Restart the browser session, optionally switching the underlying browser engine.

        Args:
            engine: Optional engine name to switch to. If None, restarts with the current engine.
            restore_url: Whether to automatically navigate to the last active URL after restart.

        Returns:
            Status message indicating successful restart.
        """
        # Save current state before closing
        current_url = None
        current_storage_state = None
        if self._tab_controller.list_tabs():
            with contextlib.suppress(Exception):
                page = self._tab_controller.get_active_page()
                current_url = page.url
                current_storage_state = await page.context.storage_state()

        # Close current session resources (tabs, observers)
        # This will also trigger context destruction via BrowserSession.close()

        # Save the old context key before closing, because close() might clear it
        old_context_key = self._context_key

        # We must CLOSE FIRST to detach loggers and close tabs, otherwise pages are still "active"
        # But we temporarily set context_key to None so close() doesn't try to destroy it
        self._context_key = None
        await self.close()

        # Now explicitly destroy the context
        if old_context_key:
            try:
                # Give the event loop a tiny moment to process the async close
                await asyncio.sleep(0.5)
                # Force release all pages in the pool to bypass the concurrency guard
                for browser_inst in self._browser_pool._browsers:
                    if old_context_key in browser_inst.page_pools:
                        pool = browser_inst.page_pools[old_context_key]
                        # Clear busy pages so destroy_context doesn't raise RuntimeError
                        pool._busy.clear()
                        # Also clear the global pages in use counter
                        self._browser_pool._current_pages_in_use = max(
                            0, self._browser_pool._current_pages_in_use - pool.active_pages_count
                        )

                # Call destroy directly instead of going through the pool method to avoid lock issues
                await self._browser_pool.destroy_context(old_context_key)
            except Exception as e:
                logger.warning(f"Failed to destroy old context during restart: {e}")

        # Also clean up the browser instance if it has no more contexts
        try:
            browsers_to_remove = []
            for browser_inst in self._browser_pool._browsers:
                if not browser_inst.contexts:
                    logger.info(f"Browser instance {browser_inst.engine} has no more contexts, closing it.")
                    # Ensure we actually close the browser process
                    if browser_inst.browser:
                        try:
                            await browser_inst.browser.close()
                        except Exception as e:
                            logger.warning(f"Error closing browser process: {e}")
                            if browser_inst._pid:
                                browser_inst.force_kill()
                    browsers_to_remove.append(browser_inst)

            for b in browsers_to_remove:
                if b in self._browser_pool._browsers:
                    self._browser_pool._browsers.remove(b)
        except Exception as e:
            logger.warning(f"Failed to close empty browser instance during restart: {e}")

        # Force remove contexts from the pool's tracking if they still exist
        try:
            for browser_inst in self._browser_pool._browsers:
                if old_context_key in browser_inst.contexts:
                    logger.warning(f"Forcing removal of context {old_context_key} from tracking")
                    del browser_inst.contexts[old_context_key]
                if old_context_key in browser_inst.page_pools:
                    del browser_inst.page_pools[old_context_key]
        except Exception:
            pass

        # Update session's engine preference
        if engine:
            from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine

            try:
                self._engine_preference = BrowserEngine(engine)
                logger.info(f"Session engine preference updated to {self._engine_preference}")
            except ValueError:
                logger.warning(f"Invalid engine '{engine}', keeping current engine preference.")

        # Re-initialize the session by requesting a new page from the pool
        # This will trigger the pool to use the updated config and engine
        # We use new_tab to bootstrap the first page
        await self.new_tab()

        # Migrate storage state to the new context
        if current_storage_state:
            with contextlib.suppress(Exception):
                new_page = self._tab_controller.get_active_page()

                # 1. Add cookies
                cookies = current_storage_state.get("cookies", [])
                if cookies:
                    await new_page.context.add_cookies(cookies)
                    logger.info(f"Successfully migrated {len(cookies)} cookies to new engine.")

                # 2. Inject localStorage using add_init_script (Zero network delay, 100% concurrency safe)
                local_storage_origins = current_storage_state.get("origins", [])
                if local_storage_origins:
                    import json

                    injected_count = 0
                    for origin_data in local_storage_origins:
                        origin = origin_data.get("origin")
                        local_storage = origin_data.get("localStorage", [])
                        if local_storage and origin:
                            # Create a self-executing JS script that only runs on the matching origin
                            ls_json = json.dumps(local_storage)
                            script = f"""
                            (() => {{
                                if (window.location.origin === '{origin}') {{
                                    const items = {ls_json};
                                    items.forEach(({{name, value}}) => localStorage.setItem(name, value));
                                }}
                            }})();
                            """
                            await new_page.context.add_init_script(script)
                            injected_count += len(local_storage)

                    logger.info(
                        f"Successfully migrated {injected_count} localStorage items to new engine via init scripts."
                    )

        # Restore state if possible
        if restore_url and current_url and current_url != "about:blank":
            try:
                await self.navigate(current_url)
                return f"Successfully restarted browser session with engine '{engine or 'default'}' and restored URL."
            except Exception as e:
                return f"Restarted browser session, but failed to restore URL: {e}"

        return f"Successfully restarted browser session with engine '{engine or 'default'}'."

    async def close(self) -> None:
        """Close session(ReleaseAll资源)"""
        if self._persistence is not None:
            await self._persistence.cleanup_expired()

        if self._recording_manager is not None:
            if self._recording_manager.trace_active:
                logger.warning("Trace recording was still active during session close, cleaning up state")
            if self._recording_manager.har_active:
                logger.warning("HAR recording was still active during session close, cleaning up state")

        video_path = None
        if self._observability and self._observability.recording_enabled:
            try:
                page = self._tab_controller.get_active_page()
                if page.video:
                    video_path = Path(await page.video.path())
            except Exception as e:
                logger.warning("Failed to get video path: %s", e)

        if self._download_manager is not None:
            await self._download_manager.cleanup()

        self._network_logger.detach_current()
        self._console_logger.detach_current()
        await self._network_intelligence.detach()

        await self._tab_controller.close_all()

        # Explicitly destroy the underlying BrowserContext to prevent memory leaks
        # We do this AFTER closing tabs so the page_pool is empty and we pass the Concurrency Guard
        if self._context_key:
            try:
                # We need to wait a tiny bit for the page release to fully complete in the event loop
                await asyncio.sleep(0.5)
                # Ensure we pass the context_key that is currently active before we switch
                ctx_to_destroy = self._context_key

                # Force release all pages in the pool to bypass the concurrency guard
                for browser_inst in self._browser_pool._browsers:
                    if ctx_to_destroy in browser_inst.page_pools:
                        pool = browser_inst.page_pools[ctx_to_destroy]
                        # Clear busy pages so destroy_context doesn't raise RuntimeError
                        pool._busy.clear()
                        # Also clear the global pages in use counter
                        self._browser_pool._current_pages_in_use = max(
                            0, self._browser_pool._current_pages_in_use - pool.active_pages_count
                        )

                await self._browser_pool.destroy_context(ctx_to_destroy)
                # Ensure we clear the context key so it's not reused
                self._context_key = None
            except Exception as e:
                logger.warning(f"Failed to destroy context during session close: {e}")

        if self._observability:
            self._observability.cleanup_recording(video_path)

        logger.info("BrowserSession: closed session")

    @staticmethod
    def _get_site_experience_hint(url: str) -> str:
        """Query site experience and format as injected text (cross-validate with DomainMetrics)."""
        try:
            from urllib.parse import urlparse

            from ...web_fetch.router import (
                get_global_domain_metrics_manager,
                get_global_site_experience_store,
            )

            domain = urlparse(url).netloc.lower()
            if not domain:
                return ""

            store = get_global_site_experience_store()
            metrics_manager = get_global_domain_metrics_manager()
            experience, possibly_stale = store.get(domain, domain_metrics_manager=metrics_manager)

            if experience is None or experience.is_empty():
                return ""

            return experience.format_for_injection(possibly_stale=possibly_stale)
        except Exception:
            return ""

    async def _initialize_components(self) -> None:
        """Initialize components (Navigator integration rate-limiting, circuit breaker and smart wait)."""
        page = self._tab_controller.get_active_page()
        tab_id = self._tab_controller.get_active_tab_id()

        from ...web_fetch.router import get_global_domain_metrics_manager

        self._navigator = Navigator(
            page,
            throttle=self._browser_pool.throttle_strategy,
            circuit_breaker=self._browser_pool.circuit_breaker,
            wait_config=self._browser_pool.config.navigation_wait,
            domain_metrics_manager=get_global_domain_metrics_manager(),
            allow_private_networks=self._allow_private_networks,
        )
        self._snapshot_manager = SnapshotManager(page)

        last_snapshot_url = self._tab_controller.get_snapshot_url(tab_id)
        self._interactor = Interactor(page, {}, last_snapshot_url=last_snapshot_url)
        self._extractor = Extractor(page)

        if not self._auto_restored and self._auto_restore_domains and self._persistence:
            self._auto_restored = True
            for domain in self._auto_restore_domains:
                try:
                    await self._persistence.restore(page.context, page, domain)
                    logger.info(f"Auto-restored session for domain: {domain}")
                except Exception as e:
                    logger.error(f"Failed to auto-restore domain {domain}: {e}")

        if self._recording_manager is None:
            self._recording_manager = RecordingManager()

        self._network_logger.start_capture(page)
        self._console_logger.start_capture(page)
        await self._network_intelligence.attach(page)

        if self._download_manager is not None:
            self._download_manager.attach(page)

        self._dialog_manager.attach(page)

    async def _ensure_components(self) -> None:
        """ensure Component already Initialize"""
        if self._navigator is None:
            await self._initialize_components()

    def _require_navigator(self) -> Navigator:
        """Ensure Navigator is initialized and return it.

        Returns:
            Navigator instance

        Raises:
            RuntimeError: If Navigator is not initialized
        """
        if self._navigator is None:
            raise RuntimeError("Navigator not initialized. Call new_tab() or navigate() first.")
        return self._navigator

    def _require_snapshot_manager(self) -> SnapshotManager:
        """Ensure SnapshotManager is initialized and return it.

        Returns:
            SnapshotManager instance

        Raises:
            RuntimeError: If SnapshotManager is not initialized
        """
        if self._snapshot_manager is None:
            raise RuntimeError("SnapshotManager not initialized. Call new_tab() first.")
        return self._snapshot_manager

    def _require_interactor(self) -> Interactor:
        """Ensure Interactor is initialized and return it.

        Returns:
            Interactor instance

        Raises:
            RuntimeError: If Interactor is not initialized
        """
        if self._interactor is None:
            raise RuntimeError("Interactor not initialized. Call new_tab() first.")
        return self._interactor

    def _require_extractor(self) -> Extractor:
        """Ensure Extractor is initialized and return it.

        Returns:
            Extractor instance

        Raises:
            RuntimeError: If Extractor is not initialized
        """
        if self._extractor is None:
            raise RuntimeError("Extractor not initialized. Call new_tab() first.")
        return self._extractor

    @property
    def stats(self) -> dict[str, object]:
        """GetStatisticsinformation

        Returns:
            Statistics information Dict, Contains:
            - tab_controller: Tab Management Statistics
            - snapshot_manager: SnapshotStatistics (If already Initialize)
            - ref_failures: Ref Failure Metrics (If already Initialize)
                - total_failures: Total failures
                - total_interactions: Total interactions
                - failure_rate: Global failure rate (0.0-1.0)
                - recent_failure_rate: Recent 100 interactions failure rate (0.0-1.0)
                - top_failed_refs: Top failed refs (descending, max 10)
                - top_failed_actions: Top failed actions (descending)
            - recording: Recording State (If already Initialize)
        """
        stats: dict[str, object] = {"tab_controller": self._tab_controller.stats}

        if self._snapshot_manager:
            stats["snapshot_manager"] = self._snapshot_manager.stats

        if self._interactor:
            stats["ref_failures"] = self._interactor.metrics.to_dict()

        if self._recording_manager:
            stats["recording"] = self._recording_manager.get_status()

        if self._download_manager:
            stats["downloads"] = len(self._download_manager.downloads)

        return stats
