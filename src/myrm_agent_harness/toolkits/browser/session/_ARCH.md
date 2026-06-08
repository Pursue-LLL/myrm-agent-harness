# session/

## Overview
Browser session components.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Browser session components. | — |
| browser_session.py | Core | Browser session manager (aggregate root). Composes TabController, Navigator, SnapshotManager, Interactor, Extractor, CaptchaCoordinator (optional). new_tab() implements origin-based routing to reuse same-origin tabs. | ✅ |
| browser_session_page_mixin.py | Core | Viewport, dialog, and misc page-level helpers for BrowserSession. | ✅ |
| browser_session_persistence_mixin.py | Core | Encrypted session save/restore API for BrowserSession. | ✅ |
| browser_session_recording_mixin.py | Core | Playwright trace and HAR recording controls for BrowserSession. | ✅ |
| download_manager.py | Core | Browser file download manager. Single responsibility: listen for, process, and record file downloads | ✅ |
| extractor.py | Core | Content extraction manager. Responsibilities: | ✅ |
| interactor.py | Core | Element interaction manager. Responsibilities: | ✅ |
| network_logger.py | Core | Network request logging for the browser toolkit. Provides self-diagnosis capability for browser sess | ✅ |
| network_intelligence.py | Core | CDP-based network intelligence for on-demand API response body retrieval and request replay. | ✅ |
| console_logger.py | Core | Browser console log capture (JS errors/warnings/logs + page errors). Mirrors NetworkLogger lifecycle. | ✅ |
| page_analyzer.py | Core | Lightweight page structure analyzer. Executes fast DOM analysis via page.evaluate(), | ✅ |
| session_persistence.py | Core | Session persistence helper class. Single responsibility: handles session save/restore/list/delete op | ✅ |
| session_lifecycle_hook.py | Protocol | SessionLifecycleHookProtocol: optional observer for session save/delete/expire events. | ✅ |
| session_memory_bridge.py | Core | SessionMemoryBridge: keeps active_browser_sessions profile attribute in sync with the vault via SessionLifecycleHookProtocol. | ✅ |
| snapshot_diff.py | Core | ARIA snapshottext'ssemantic diff(ref prefixnormalizeafterlinelevelfor). | ✅ |
| snapshot_manager.py | Core | Snapshot generation manager. Responsibilities: | ✅ |
| snapshot_result.py | Core | Immutable snapshot result type for browser ARIA snapshots. | ✅ |
| snapshot_suggestion.py | Core | Heuristic token / scope suggestions for large ARIA snapshots. | ✅ |
| tab_controller.py | Core | Tab lifecycle manager. Responsibilities: create/close tabs, switch active tab, LRU eviction, origin-based tab routing (find_tab_by_origin), domain-aware tab listing (list_tabs_with_info). | ✅ |
| vision_verifier.py | Core | 3-Layer Vision Verifier for Action-Verification Fusion. | ✅ |
| structured_extractor.py | Core | LLM-based structured data extraction using JSON Schema → Pydantic validation. | ✅ |

## Key Dependencies

- `core`
