"""Browser automation toolkit — interactive browser control for agents.

Provides ``BrowserSession`` (multi-tab lifecycle, iframe traversal, automatic
event handling). LangChain tools are available via myrm_agent_harness.toolkits.

Reuses the existing ``ManagedBrowser`` (Patchright) infrastructure.


[INPUT]
- session::BrowserSession (POS: multi-tab browser session manager)
- session::ElementRef (POS: element reference with frame context)
- domain_filter::DomainAllowlist (POS: immutable domain allowlist matcher)
- screenshot_diff::DiffResult (POS: immutable screenshot comparison result)
- session_vault::SessionVault (POS: AES-256-GCM encrypted session storage)
- session_vault::SessionEntry (POS: immutable session record)
- session_vault::SessionSummary (POS: lightweight session metadata without sensitive data)
- exceptions::BrowserError (POS: browser toolkit root exception)
- observability::BrowserObservability (POS: browser observability manager)
- observability::RecordingConfig (POS: recording configuration)

[OUTPUT]
- BrowserSession: multi-tab browser session manager (re-export)
- ElementRef: element reference with frame context (re-export)
- DomainAllowlist: immutable domain allowlist matcher (re-export)
- DiffResult: immutable screenshot comparison result (re-export)
- SessionVault: AES-256-GCM encrypted session storage (re-export)
- SessionEntry: immutable session record (re-export)
- SessionSummary: lightweight session metadata without sensitive data (re-export)
- EmulationConfig: type-safe browser environment emulation config (re-export)
- BrowserError + 11-subclass exception hierarchy (root + 6 subclasses re-exported; ClickTargetUnreachableError + AriaError family stay internal)
- BrowserObservability: browser observability manager (re-export)
- RecordingConfig: recording configuration (re-export)
- ActionCaptureEngine: browser action capture engine (re-export)
- ActionStep: captured browser action (re-export)
- ActionType: capturable action types (re-export)
- CaptureSession: recording session state (re-export)
- CaptureCallback: real-time step notification protocol (re-export)
- run_doctor: 浏览器环境诊断编排器（re-export, doctor 子包）
- format_report: 诊断报告 CLI 渲染（re-export, doctor 子包）
- find_orphan_chromium_processes / find_orphan_driver_processes / find_orphan_automation_processes: 孤儿进程检测（re-export, doctor 子包）
- cleanup_orphan_processes: 孤儿进程安全清理（re-export, doctor 子包）

Note: create_browser_tools lives in the myrm_agent_harness.toolkits module

[POS]
Browser toolkit public entry point. Aggregates and exports the module's core API
for unified external consumer imports.
"""

from typing import TYPE_CHECKING

from .domain_filter import DomainAllowlist
from .exceptions import (
    BrowserError,
    BrowserLaunchError,
    BrowserNavigationError,
    BrowserPoolError,
    BrowserSessionError,
    BrowserToolError,
    RefNotFoundError,
)
from .pool import EmulationConfig
from .session import BrowserSession

if TYPE_CHECKING:
    from .action_capture import (
        ActionCaptureEngine,
        ActionStep,
        ActionType,
        CaptureCallback,
        CaptureSession,
    )
    from .checkpoint import (
        AutoRecoveryOrchestrator,
        BrowserCheckpointHelper,
        CheckpointMetadata,
        CheckpointMetrics,
        IncrementalSessionCheckpointer,
        ParallelRecoveryOrchestrator,
        RecoveryContext,
        create_browser_context_updater,
        extract_metadata_from_messages,
        get_browser_state,
        merge_metadata,
        restore_browser_state,
    )
    from .doctor import (
        CheckStatus,
        DoctorCheckResult,
        DoctorReport,
        cleanup_orphan_processes,
        find_orphan_automation_processes,
        find_orphan_chromium_processes,
        find_orphan_driver_processes,
        format_report,
        run_doctor,
    )
    from .observability import BrowserObservability, RecordingConfig
    from .spaces import BrowserTaskSpace, HarnessTaskSpaceManager
    from .session_vault import (
        CorruptedSessionError,
        DecryptionError,
        EncryptionError,
        InvalidDomainError,
        SessionEntry,
        SessionSummary,
        SessionVault,
        SessionVaultError,
        VaultMetrics,
    )

__all__ = [
    "ActionCaptureEngine",
    "ActionStep",
    "ActionType",
    "AutoRecoveryOrchestrator",
    "BrowserCheckpointHelper",
    "BrowserError",
    "BrowserLaunchError",
    "BrowserNavigationError",
    "BrowserObservability",
    "BrowserPoolError",
    "BrowserSession",
    "BrowserSessionError",
    "BrowserTaskSpace",
    "BrowserToolError",
    "CaptureCallback",
    "CaptureSession",
    "CheckStatus",
    "CheckpointMetadata",
    "CheckpointMetrics",
    "CorruptedSessionError",
    "DecryptionError",
    "DoctorCheckResult",
    "DoctorReport",
    "DomainAllowlist",
    "EmulationConfig",
    "EncryptionError",
    "FileVaultBackend",
    "HarnessTaskSpaceManager",
    "IncrementalSessionCheckpointer",
    "InvalidDomainError",
    "ParallelRecoveryOrchestrator",
    "RecordingConfig",
    "RecoveryContext",
    "RefNotFoundError",
    "SessionEntry",
    "SessionSummary",
    "SessionVault",
    "SessionVaultBackend",
    "SessionVaultError",
    "StorageVaultBackend",
    "VaultMetrics",
    "cleanup_orphan_processes",
    "create_browser_context_updater",
    "extract_metadata_from_messages",
    "find_orphan_automation_processes",
    "find_orphan_chromium_processes",
    "find_orphan_driver_processes",
    "format_report",
    "get_browser_state",
    "load_or_create_key",
    "merge_metadata",
    "restore_browser_state",
    "run_doctor",
]

_LAZY_MODULES = {
    "checkpoint": [
        "IncrementalSessionCheckpointer",
        "CheckpointMetadata",
        "CheckpointMetrics",
        "AutoRecoveryOrchestrator",
        "ParallelRecoveryOrchestrator",
        "RecoveryContext",
        "BrowserCheckpointHelper",
        "extract_metadata_from_messages",
        "merge_metadata",
        "get_browser_state",
        "restore_browser_state",
        "create_browser_context_updater",
    ],
    "doctor.checks": [
        "run_doctor",
    ],
    "doctor.orphans": [
        "cleanup_orphan_processes",
        "find_orphan_automation_processes",
        "find_orphan_chromium_processes",
        "find_orphan_driver_processes",
    ],
    "doctor.report": [
        "CheckStatus",
        "DoctorCheckResult",
        "DoctorReport",
        "format_report",
    ],
    "session_vault": [
        "SessionVault",
        "SessionEntry",
        "SessionSummary",
        "VaultMetrics",
        "SessionVaultError",
        "InvalidDomainError",
        "EncryptionError",
        "DecryptionError",
        "CorruptedSessionError",
    ],
    "session_vault.backends.file_backend": ["FileVaultBackend", "load_or_create_key"],
    "session_vault.backends.protocols": ["SessionVaultBackend"],
    "session_vault.backends.storage_backend": ["StorageVaultBackend"],
    "observability": ["BrowserObservability", "RecordingConfig"],
    "action_capture": [
        "ActionCaptureEngine",
        "ActionStep",
        "ActionType",
        "CaptureCallback",
        "CaptureSession",
    ],
    "spaces": [
        "BrowserTaskSpace",
        "HarnessTaskSpaceManager",
    ],
}

_SYMBOL_TO_MODULE = {symbol: module_name for module_name, symbols in _LAZY_MODULES.items() for symbol in symbols}

if __debug__:
    _all_lazy_symbols = {symbol for symbols in _LAZY_MODULES.values() for symbol in symbols}
    _all_set = set(__all__)
    _extra = _all_lazy_symbols - _all_set
    if _extra:
        raise RuntimeError(f"browser: _LAZY_MODULES has symbols not in __all__: {_extra}")


def __getattr__(name: str):
    """Lazy load checkpoint, doctor, vault, and observability modules."""
    from importlib import import_module

    module_name = _SYMBOL_TO_MODULE.get(name)
    if module_name:
        module = import_module(f".{module_name}", package=__name__)
        symbols = _LAZY_MODULES[module_name]
        for symbol in symbols:
            globals()[symbol] = getattr(module, symbol)
        return globals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
