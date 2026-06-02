"""Browser session components.

Single-responsibility components following SOLID principles.

Note: Navigator has been moved to myrm_agent_harness.toolkits.browser.navigation
to be reusable by both BrowserSession and BrowserFetcher.
"""

from .browser_session import BrowserSession
from .download_manager import DownloadConfig, DownloadManager, DownloadResult
from .extractor import Extractor
from .interactor import Interactor
from .snapshot_manager import SnapshotManager
from .tab_controller import TabController

__all__ = [
    "BrowserSession",
    "DownloadConfig",
    "DownloadManager",
    "DownloadResult",
    "Extractor",
    "Interactor",
    "SnapshotManager",
    "TabController",
]
