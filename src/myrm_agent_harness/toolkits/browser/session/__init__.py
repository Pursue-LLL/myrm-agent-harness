"""Browser session components.

Single-responsibility components following SOLID principles. Navigator lives in
``toolkits/browser/navigation``, shared by BrowserSession and BrowserFetcher.
"""

from .browser_session import BrowserSession
from .browser_session_extraction_mixin import ContentVault
from .consent_dismisser import ConsentDismisser
from .dialog_manager import DialogManager, DialogPolicy
from .download_manager import DownloadConfig, DownloadManager, DownloadResult
from .extractor import Extractor
from .interactor import Interactor
from .session_lifecycle_hook import SessionLifecycleHookProtocol
from .session_memory_bridge import SessionMemoryBridge
from .snapshot_manager import SnapshotManager
from .structured_extractor import StructuredExtractor
from .tab_controller import TabController

__all__ = [
    "BrowserSession",
    "ConsentDismisser",
    "ContentVault",
    "DialogManager",
    "DialogPolicy",
    "DownloadConfig",
    "DownloadManager",
    "DownloadResult",
    "Extractor",
    "Interactor",
    "SessionLifecycleHookProtocol",
    "SessionMemoryBridge",
    "SnapshotManager",
    "StructuredExtractor",
    "TabController",
]
