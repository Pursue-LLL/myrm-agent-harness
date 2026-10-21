"""Typed host contract of the BrowserSession mixins.

[INPUT]
- session.tab_controller::TabController (POS: tab lifecycle management)
- navigation::Navigator (POS: throttled page navigation)
- session.snapshot_manager::SnapshotManager, SnapshotResult (POS: snapshot generation)
- session.interactor::Interactor, session.extractor::Extractor (POS: element interaction, content extraction)
- session.console_logger / network_logger / network_intelligence / dialog_manager / device_emulator / consent_dismisser / vision_verifier (POS: per-page components owned by the aggregate root)
- pool::GlobalBrowserPool, pool.extension_bridge::ExtensionBridge (POS: browser pool, user-browser extension bridge)
- observability::BrowserObservability, recording_manager::RecordingManager, session.download_manager::DownloadManager, session.session_persistence::SessionPersistence (POS: optional per-session services owned by the aggregate root)
- captcha::CaptchaCoordinator (POS: CAPTCHA detection and solving coordination)

[OUTPUT]
- SessionHost: base of the navigation, tab, CAPTCHA, network and lifecycle mixins; declares the attributes and
  methods the BrowserSession aggregate root and its mixins provide to one another. Type-checking only: at
  runtime it is `object`, so the MRO of BrowserSession is unchanged.

[POS]
Single typed declaration of what a session mixin may rely on from its host, so a mixin does not
repeat attribute stubs and a signature drift in the aggregate root fails type checking instead of
failing at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..captcha import CaptchaCoordinator
    from ..navigation import Navigator
    from ..observability import BrowserObservability
    from ..pool import GlobalBrowserPool
    from ..pool.config import BrowserEngine, LaunchMode
    from ..pool.extension_bridge import ExtensionBridge
    from ..recording_manager import RecordingManager
    from .consent_dismisser import ConsentDismisser
    from .console_logger import ConsoleLogger
    from .device_emulator import DeviceEmulator
    from .dialog_manager import DialogManager
    from .download_manager import DownloadManager
    from .extractor import Extractor
    from .interactor import Interactor
    from .network_intelligence import NetworkIntelligence
    from .network_logger import NetworkLogger
    from .session_persistence import SessionPersistence
    from .snapshot_manager import SnapshotManager, SnapshotResult
    from .tab_controller import TabController
    from .vision_verifier import VisionVerifier

    class SessionHost:
        _browser_pool: GlobalBrowserPool
        _extension_bridge: ExtensionBridge | None
        _allow_private_networks: bool
        _context_key: str | None
        _observability: BrowserObservability | None
        _auto_restore_domains: list[str]
        _auto_restored: bool
        _engine_preference: BrowserEngine | None
        _launch_mode_preference: LaunchMode | None
        _user_takeover_active: bool
        _terminal_challenges: dict[str, float]
        _captcha_coordinator: CaptchaCoordinator | None
        _consent_dismisser: ConsentDismisser
        _vision_verifier: VisionVerifier
        _tab_controller: TabController
        _device_emulator: DeviceEmulator
        _network_logger: NetworkLogger
        _console_logger: ConsoleLogger
        _network_intelligence: NetworkIntelligence
        _dialog_manager: DialogManager
        _persistence: SessionPersistence | None
        _recording_manager: RecordingManager | None
        _download_manager: DownloadManager | None
        _session_hash_cache: dict[str, str]
        _navigator: Navigator | None
        _snapshot_manager: SnapshotManager | None
        _interactor: Interactor | None
        _extractor: Extractor | None

        async def _initialize_components(self) -> None: ...
        async def _ensure_components(self) -> None: ...
        async def _ensure_not_user_takeover(self, timeout: float = 600.0) -> None: ...
        async def _publish_inspector_view(
            self, *, snapshot_result: SnapshotResult | None = None, force: bool = False
        ) -> None: ...
        def _require_navigator(self) -> Navigator: ...
        def _require_snapshot_manager(self) -> SnapshotManager: ...
        def is_browser_managed(self) -> bool: ...
        async def navigate(self, url: str, verify_goal: str | None = None) -> str: ...
        async def new_tab(self, url: str | None = None) -> str: ...
        async def restart(self, engine: str | None = None, restore_url: bool = True) -> str: ...
        async def notify_progress(self, message: str) -> None: ...
        async def snapshot(
            self,
            *,
            scope: str = "content",
            compact: bool = False,
            max_tokens: int = 0,
            diff: bool = True,
            update_baseline: bool = True,
        ) -> SnapshotResult: ...
else:
    SessionHost = object
