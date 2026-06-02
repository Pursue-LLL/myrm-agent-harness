# session/

## Overview
Browser session components.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Browser session components. | — |
| browser_session.py | Core | Browser session manager (aggregate root). Composes TabController, Navigator, SnapshotManager, Interactor, Extractor, CaptchaCoordinator (optional). | ✅ |
| browser_session_page_mixin.py | Core | Viewport, dialog, and misc page-level helpers for BrowserSession. | ✅ |
| browser_session_persistence_mixin.py | Core | Encrypted session save/restore API for BrowserSession. | ✅ |
| browser_session_recording_mixin.py | Core | Playwright trace and HAR recording controls for BrowserSession. | ✅ |
| download_manager.py | Core | Browser file download manager. Single responsibility: listen for, process, and record file downloads | ✅ |
| extractor.py | Core | Content extraction manager. Responsibilities: | ✅ |
| interactor.py | Core | Element interaction manager. Responsibilities: | ✅ |
| network_logger.py | Core | Network request logging for the browser toolkit. Provides self-diagnosis capability for browser sess | ✅ |
| console_logger.py | Core | Browser console log capture (JS errors/warnings/logs + page errors). Mirrors NetworkLogger lifecycle. | ✅ |
| page_analyzer.py | Core | Lightweight page structure analyzer. Executes fast DOM analysis via page.evaluate(), | ✅ |
| session_persistence.py | Core | Session persistence helper class. Single responsibility: handles session save/restore/list/delete op | ✅ |
| snapshot_diff.py | Core | ARIA snapshottext'ssemantic diff(ref prefixnormalizeafterlinelevelfor). | ✅ |
| snapshot_manager.py | Core | Snapshot generation manager. Responsibilities: | ✅ |
| snapshot_result.py | Core | Immutable snapshot result type for browser ARIA snapshots. | ✅ |
| snapshot_suggestion.py | Core | Heuristic token / scope suggestions for large ARIA snapshots. | ✅ |
| tab_controller.py | Core | Tab lifecycle manager. Responsibilities: | ✅ |
| vision_verifier.py | Core | 3-Layer Vision Verifier for Action-Verification Fusion. | ✅ |

## Key Dependencies

- `core`
