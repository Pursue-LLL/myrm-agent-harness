# video/

## Overview
Video generation module — multi-provider video generation with failover.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Video generation module — multi-provider video generation with failover. | ✅ |
| `_helpers.py` | Internal | Used by generator.py for retry logic, error formatting, content validation, and non-retryable classification (including ModerationBlockedError). | ✅ |
| `generator.py` | Core | Video generation orchestrator with ModerationBlockedError fast-fail dispatch. | ✅ |
| `models.py` | Core | Pure data types with no business logic. Includes ModerationBlockedError and ProviderCapabilities. | ✅ |
| `task_store.py` | Core | Framework provides Protocol + two implementations (in-memory default, file-based). | ✅ |
| `async_video_engine.py` | Core | Async enqueue adapter (`task_id` immediate return) for non-blocking video generation. | ✅ |
| `video_engine.py` | Core | Video generation engine; LangChain adapter in server `media_tools/`. | ✅ |

| Submodule | Description |
|-----------|-------------|
| providers/ | Video generation providers — pluggable backends for video generation. |

## Key Dependencies

- `core.security.http.secure_fetch` (secure_get/secure_request for user/model result URL downloads in `video_engine` and all providers, with `max_content_length` cap and `ContentTooLargeError` handling)
- `core`
