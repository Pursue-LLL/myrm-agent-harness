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
- session.browser_session_extraction_mixin::BrowserSessionExtractionMixin (POS: content extraction and screenshot compare APIs)
- session.browser_session_page_mixin::BrowserSessionPageMixin (POS: viewport/dialog/JS and other page-level APIs)
- session.browser_session_persistence_mixin::BrowserSessionPersistenceMixin (POS: SessionVault persistence API)
- session.browser_session_recording_mixin::BrowserSessionRecordingMixin (POS: trace/HAR recording API)
- session.browser_session_navigation_mixin::BrowserSessionNavigationMixin (POS: navigation, tab switching, CAPTCHA)
- session.browser_session_lifecycle_mixin::BrowserSessionLifecycleMixin (POS: restart/close and component init)
- session.browser_session_network_mixin::BrowserSessionNetworkMixin (POS: console and network log APIs)
- session.download_manager::DownloadManager, DownloadConfig (POS: file download management)
- session.dialog_manager::DialogManager, DialogPolicy (POS: JS dialog lifecycle management)

[OUTPUT]
- BrowserSession: browser session manager (aggregate root)
  - snapshot(...) -> SnapshotResult: generate ARIA snapshot (frozen dataclass, immutable)
  - extract_text(...) -> str: extract page text with pagination support
  - extract_structured(...) -> str: extract structured JSON data via LLM + JSON Schema
  - extract_media(...) -> str: extract high-value media resource URLs (images/videos/audio)
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
14. ConsentDismisser (cookie consent auto-accept after navigation, zero LLM cost)

The aggregate root class combines mixins via multiple inheritance (Persistence, Recording, Extraction,
Page, Network, Navigation, Lifecycle). MRO order is fixed: Network before Navigation before Lifecycle
so navigate() can call _initialize_components and restart().
"""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.browser.observability import BrowserObservability
from myrm_agent_harness.toolkits.browser.recording_manager import RecordingManager
from myrm_agent_harness.toolkits.browser.utils.selectors import PASSWORD_FIELD_SELECTOR

from ..navigation import Navigator
from .browser_session_extraction_mixin import BrowserSessionExtractionMixin, ContentVault
from .browser_session_lifecycle_mixin import BrowserSessionLifecycleMixin
from .browser_session_navigation_mixin import BrowserSessionNavigationMixin
from .browser_session_network_mixin import BrowserSessionNetworkMixin
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
    from myrm_agent_harness.toolkits.browser.pool.extension_bridge import ExtensionBridge
    from myrm_agent_harness.toolkits.browser.session_vault import SessionVault
    from myrm_agent_harness.toolkits.browser.snapshot import RefInfo

logger = logging.getLogger(__name__)


class BrowserSession(
    BrowserSessionPersistenceMixin,
    BrowserSessionRecordingMixin,
    BrowserSessionExtractionMixin,
    BrowserSessionPageMixin,
    BrowserSessionNetworkMixin,
    BrowserSessionNavigationMixin,
    BrowserSessionLifecycleMixin,
):
    """Browser session manager (aggregate root)

    Composes TabController, Navigator, SnapshotManager, Interactor, Extractor, NetworkLogger,
    SessionPersistence, and optional CAPTCHA/download subsystems via mixins.
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
        extension_bridge: ExtensionBridge | None = None,
        *,
        allow_private_networks: bool = False,
        engine_preference: str | None = None,
        launch_mode_preference: str | None = None,
        dialog_policy: str | None = None,
        auto_dismiss_consent: bool = True,
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
            extension_bridge: Extension bridge for private URL fallback in sandbox mode
            allow_private_networks: Allow navigation to private networks
            engine_preference: Preferred browser engine (e.g. 'chromium_patchright', 'firefox_camoufox').
            launch_mode_preference: Per-agent launch mode override (e.g. 'extension' to use user's real browser).
            dialog_policy: Dialog handling strategy ('smart', 'auto_accept', 'auto_dismiss', 'wait_for_agent').
            auto_dismiss_consent: Auto-accept cookie consent banners after navigation (default True).
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
        self._extension_bridge = extension_bridge
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
        self._hitl_caller_tool: str | None = None
        self._content_vault = content_vault
        self._vision_verifier = VisionVerifier(vision_llm)
        self._structured_extractor = StructuredExtractor(vision_llm)
        self._vision_llm = vision_llm

        self._session_lifecycle_hook = None

        # CAPTCHA coordination (optional — only active when a solver is provided)
        if captcha_solver is not None:
            from myrm_agent_harness.toolkits.browser.captcha import CaptchaCoordinator

            self._captcha_coordinator: CaptchaCoordinator | None = CaptchaCoordinator(captcha_solver)
        else:
            self._captcha_coordinator = None

        # Terminal challenge memory: domain → monotonic timestamp.
        # After CAPTCHA+CAMOUFOX both fail, the domain is recorded here.
        # Subsequent navigations to the same domain skip the 240s timeout
        # and return ToolError immediately (fast-fail). TTL: 10 minutes.
        self._terminal_challenges: dict[str, float] = {}

        # Dialog handling (always active — default SMART policy)
        try:
            policy = DialogPolicy(dialog_policy) if dialog_policy else DialogPolicy.SMART
        except ValueError:
            logger.warning(f"Invalid dialog_policy '{dialog_policy}', falling back to SMART.")
            policy = DialogPolicy.SMART
        self._dialog_manager = DialogManager(policy=policy)

        # Cookie consent auto-dismisser (active by default)
        from myrm_agent_harness.toolkits.browser.session.consent_dismisser import ConsentDismisser

        self._consent_dismisser = ConsentDismisser(enabled=auto_dismiss_consent)
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

        from myrm_agent_harness.toolkits.browser.tools.semantic_dom_hitl import (
            enforce_semantic_interaction_guard,
        )

        ref_info = self.get_ref_info(ref)
        caller_tool = self._hitl_caller_tool or "browser_interact_tool"
        blocked = await enforce_semantic_interaction_guard(
            session=self,
            tool_name=caller_tool,
            action=action,
            ref=ref,
            ref_info=ref_info,
            text=text,
        )
        if blocked is not None:
            return blocked

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
            captcha_result = await self._handle_captcha_if_detected()
            if captcha_result is not None:
                result = f"{result}\n{captcha_result.message}"

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

    async def notify_progress(self, message: str) -> None:
        """Send progress notification to observability hook and agent SSE stream."""
        if self._observability:
            await self._observability.notify_progress(message)

        from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

        sink = get_tool_progress_sink()
        if sink is not None:
            await sink.emit(
                {
                    "type": "status",
                    "step_key": "workflow_stage",
                    "status": "in_progress",
                    "data": {
                        "message": message,
                        "notify_progress": -1,
                        "notify_step_index": 0,
                        "notify_total_steps": 0,
                        "notify_category": "browser",
                        "notify_level": "info",
                    },
                }
            )

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
