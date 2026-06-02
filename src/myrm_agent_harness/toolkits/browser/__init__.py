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
- exceptions::BrowserError (POS: browser toolkit root exception)
- retry_policy::RetryPolicy (POS: retry policy framework)
- observability::BrowserObservability (POS: browser observability manager)
- observability::RecordingConfig (POS: recording configuration)

[OUTPUT]
- BrowserSession: multi-tab browser session manager (re-export)
- ElementRef: element reference with frame context (re-export)
- DomainAllowlist: immutable domain allowlist matcher (re-export)
- DiffResult: immutable screenshot comparison result (re-export)
- SessionVault: AES-256-GCM encrypted session storage (re-export)
- SessionEntry: immutable session record (re-export)
- EmulationConfig: type-safe browser environment emulation config (re-export)
- BrowserError + 12 subclasses: exception type hierarchy (re-export)
- RetryPolicy + 3 subclasses: retry policy classes (re-export)
- BrowserObservability: browser observability manager (re-export)
- RecordingConfig: recording configuration (re-export)

Note: create_browser_tools lives in the myrm_agent_harness.toolkits module

[POS]
Browser toolkit public entry point. Aggregates and exports the module's core API
for unified external consumer imports.
"""

from typing import TYPE_CHECKING

from .domain_filter import DomainAllowlist
from .exceptions import (
    BrowserClosedError,
    BrowserError,
    BrowserLaunchError,
    BrowserNavigationError,
    BrowserNetworkError,
    BrowserPoolError,
    BrowserPoolExhaustedError,
    BrowserSessionError,
    BrowserShutdownError,
    BrowserTimeoutError,
    BrowserToolError,
    RefNotFoundError,
    ToolConfigurationError,
    ToolExecutionError,
)
from .pool import EmulationConfig
from .retry_policy import (
    LaunchRetryPolicy,
    NavigationRetryPolicy,
    NetworkRetryPolicy,
    RetryPolicy,
)
from .session import BrowserSession

if TYPE_CHECKING:
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
        find_orphan_chromium_processes,
        format_report,
        run_doctor,
    )
    from .observability import BrowserObservability, RecordingConfig
    from .session_vault import SessionVault
    from .session_vault_exceptions import (
        CorruptedSessionError,
        DecryptionError,
        EncryptionError,
        InvalidDomainError,
        SessionVaultError,
    )
    from .session_vault_types import SessionEntry, VaultMetrics

__all__ = [
    "AutoRecoveryOrchestrator",
    "BrowserCheckpointHelper",
    "BrowserClosedError",
    "BrowserError",
    "BrowserLaunchError",
    "BrowserNavigationError",
    "BrowserNetworkError",
    "BrowserObservability",
    "BrowserPoolError",
    "BrowserPoolExhaustedError",
    "BrowserSession",
    "BrowserSessionError",
    "BrowserShutdownError",
    "BrowserTimeoutError",
    "BrowserToolError",
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
    "IncrementalSessionCheckpointer",
    "InvalidDomainError",
    "LaunchRetryPolicy",
    "NavigationRetryPolicy",
    "NetworkRetryPolicy",
    "ParallelRecoveryOrchestrator",
    "RecordingConfig",
    "RecoveryContext",
    "RefNotFoundError",
    "RetryPolicy",
    "SessionEntry",
    "SessionVault",
    "SessionVaultBackend",
    "SessionVaultError",
    "StorageVaultBackend",
    "ToolConfigurationError",
    "ToolExecutionError",
    "VaultMetrics",
    "cleanup_orphan_processes",
    "create_browser_context_updater",
    "extract_metadata_from_messages",
    "find_orphan_chromium_processes",
    "format_report",
    "get_browser_state",
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
    "doctor": [
        "CheckStatus",
        "DoctorCheckResult",
        "DoctorReport",
        "run_doctor",
        "format_report",
        "find_orphan_chromium_processes",
        "cleanup_orphan_processes",
    ],
    "session_vault": ["SessionVault"],
    "session_vault_types": ["SessionEntry", "VaultMetrics"],
    "backends.file_backend": ["FileVaultBackend"],
    "backends.protocol": ["SessionVaultBackend"],
    "backends.storage_backend": ["StorageVaultBackend"],
    "session_vault_exceptions": [
        "SessionVaultError",
        "InvalidDomainError",
        "EncryptionError",
        "DecryptionError",
        "CorruptedSessionError",
    ],
    "observability": ["BrowserObservability", "RecordingConfig"],
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
