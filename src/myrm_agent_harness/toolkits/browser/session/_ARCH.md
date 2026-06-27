# session/

## Overview
Browser session components.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Browser session components. | — |
| browser_session.py | Core | Browser session manager (aggregate root). Composes TabController, Navigator, SnapshotManager, Interactor, Extractor, CaptchaCoordinator (optional). new_tab() implements origin-based routing to reuse same-origin tabs. close() auto-saves sessions for auto_restore_domains (hash-diff to skip unchanged, triggers SessionLifecycleHook for memory sync). | ✅ |
| browser_session_page_mixin.py | Core | Viewport, dialog, and misc page-level helpers for BrowserSession. | ✅ |
| consent_dismisser.py | Core | Cookie consent auto-dismisser. 7-phase strategy: CMP-specific buttons (75+ selectors), generic attributes, multilingual text matching (14 languages), Shadow DOM CMPs, CMP JS APIs (Didomi/Cookiebot/Osano/Klaro), force-remove CMP containers (55+ selectors + iframe cleanup), scroll restoration. Also hooked into Navigator for L2 web_fetch coverage. Zero LLM cost, ~50ms. | ✅ |
| browser_session_persistence_mixin.py | Core | Encrypted session save/restore API for BrowserSession. | ✅ |
| browser_session_recording_mixin.py | Core | Playwright trace and HAR recording controls for BrowserSession. | ✅ |
| download_manager.py | Core | Browser file download manager. Single responsibility: listen for, process, and record file downloads | ✅ |
| extractor.py | Core | Content extraction manager. Text extraction (DOM→Markdown with SVG text/tspan support), screenshot capture, media resource extraction (images/videos/audio URLs with intelligent filtering), visual content detection, and automatic Vision LLM fallback for Canvas-heavy pages. | ✅ |
| humanize.py | Core | Humanized interaction helpers. Delay calculation (uniform for FAST, Gaussian for DEFAULT/CAREFUL) and cubic Bézier mouse trajectory generation (ease-in-out, wobble, burst pauses, overshoot). | ✅ |
| interactor.py | Core | Element interaction manager. 14 action types (click/dblclick/type/fill/press/hover/focus/select/scroll/scroll_to_bottom/upload_file/drag/check/uncheck). Includes ref resolution, self-healing, SPA wait, and ref-not-found diagnosis with context sampling. scroll_to_bottom provides smart infinite scroll with scrollHeight stabilization detection. Humanized interaction via HumanizeConfig: Gaussian delay distribution (DEFAULT/CAREFUL) + Bézier mouse trajectory with wobble and overshoot (CAREFUL). | ✅ |
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
