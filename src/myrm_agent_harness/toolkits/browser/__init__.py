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
- BrowserError + 13-subclass exception hierarchy (root + 7 subclasses re-exported, including EngineUnavailableError; ClickTargetUnreachableError, UserTakeoverTimeoutError and the AriaError family stay internal)
- BrowserObservability: browser observability manager (re-export)
- RecordingConfig: recording configuration (re-export)
- ActionCaptureEngine: browser action capture engine (re-export)
- ActionStep: captured browser action (re-export)
- ActionType: capturable action types (re-export)
- CaptureSession: recording session state (re-export)
- CaptureCallback: real-time step notification protocol (re-export)
- run_doctor: 浏览器环境诊断编排器（re-export, doctor 子包）
- format_report: 诊断报告 CLI 渲染（re-export, doctor 子包）
- find_orphan_automation_processes: 孤儿进程检测（re-export, doctor 子包）
- cleanup_orphan_processes: 孤儿进程安全清理（re-export, doctor 子包）
- cleanup_stale_automation_sandboxes: 过期自动化沙箱清理（re-export, doctor 子包）

Note: create_browser_tools lives in the myrm_agent_harness.toolkits module

[POS]
Browser toolkit public entry point. Aggregates and exports the module's core API
for unified external consumer imports.
"""

from typing import TYPE_CHECKING

from .decision_discipline import (
    BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK,
    BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK,
    BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT,
    BrowserActionKind,
    BrowserNextStepDecisionRulebookAndTextOutputContractSuite,
    DecisionEvaluationResult,
    DisciplineRulebookConfig,
    ElementState,
    TextOutputContractResult,
    parse_and_validate_text_contract,
    validate_next_step_action,
    validate_target_element,
)
from .domain_filter import DomainAllowlist
from .exceptions import (
    BrowserError,
    BrowserLaunchError,
    BrowserNavigationError,
    BrowserPoolError,
    BrowserSessionError,
    BrowserToolError,
    EngineUnavailableError,
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
    from .doctor import (
        CheckStatus,
        DoctorCheckResult,
        DoctorReport,
        cleanup_orphan_processes,
        cleanup_stale_automation_sandboxes,
        find_orphan_automation_processes,
        format_report,
        run_doctor,
    )
    from .observability import BrowserObservability, RecordingConfig
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
    from .spaces import BrowserTaskSpace, HarnessTaskSpaceManager

__all__ = [
    "ActionCaptureEngine",
    "ActionStep",
    "ActionType",
    "BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK",
    "BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK",
    "BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT",
    "BrowserActionKind",
    "BrowserError",
    "BrowserLaunchError",
    "BrowserNavigationError",
    "BrowserNextStepDecisionRulebookAndTextOutputContractSuite",
    "BrowserObservability",
    "BrowserPoolError",
    "BrowserSession",
    "BrowserSessionError",
    "BrowserTaskSpace",
    "BrowserToolError",
    "CaptureCallback",
    "CaptureSession",
    "CheckStatus",
    "CorruptedSessionError",
    "DecisionEvaluationResult",
    "DecryptionError",
    "DisciplineRulebookConfig",
    "DoctorCheckResult",
    "DoctorReport",
    "DomainAllowlist",
    "ElementState",
    "EmulationConfig",
    "EncryptionError",
    "EngineUnavailableError",
    "FileVaultBackend",
    "HarnessTaskSpaceManager",
    "InvalidDomainError",
    "RecordingConfig",
    "RefNotFoundError",
    "SessionEntry",
    "SessionSummary",
    "SessionVault",
    "SessionVaultBackend",
    "SessionVaultError",
    "StorageVaultBackend",
    "TextOutputContractResult",
    "VaultMetrics",
    "cleanup_orphan_processes",
    "cleanup_stale_automation_sandboxes",
    "parse_and_validate_text_contract",
    "validate_next_step_action",
    "validate_target_element",
    "find_orphan_automation_processes",
    "format_report",
    "load_or_create_key",
    "run_doctor",
]

_LAZY_MODULES = {
    "doctor.checks": [
        "run_doctor",
    ],
    "doctor.orphans": [
        "cleanup_orphan_processes",
        "find_orphan_automation_processes",
    ],
    "doctor.sandboxes": [
        "cleanup_stale_automation_sandboxes",
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


def __getattr__(name: str) -> object:
    """Lazy load doctor, vault, observability, capture, and spaces modules."""
    from importlib import import_module

    module_name = _SYMBOL_TO_MODULE.get(name)
    if module_name:
        module = import_module(f".{module_name}", package=__name__)
        symbols = _LAZY_MODULES[module_name]
        for symbol in symbols:
            globals()[symbol] = getattr(module, symbol)
        return globals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
