# utils/

## Overview
Utility library exports. Public interface for the utils module providing commonly used helper functions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Utility library exports. Public interface for the utils module providing commonly used helper functi | ✅ |
| chat_utils.py | Core | Chat utility functions. Provides business-config-independent chat history conversion and content text extraction: `extract_text_content` (str / block-list / JSON), `extract_answer_text` (LLM 响应答案提取，先剥离内联 think 标签块，再兼容 reasoning 模型 content 空时回退 `reasoning_content`) and `extract_litellm_answer_text` (litellm 原生 `acompletion` 响应文本提取，兼容 `choices[0].message.content` / Anthropic 块列表 / `reasoning_content` 回退); plus LLM reply JSON extraction `parse_llm_json_object` / `parse_llm_json_list` (容错提取 JSON 对象/数组：兼容 markdown fence、prose 包裹、字符串内裸控制字符、尾逗号，多候选时取最后可解析容器；`parse_llm_json_object` 支持 `require_key` 过滤——仅取含指定键的对象，供 verifier/语义判定等"必须含某字段"契约复用). | ✅ |
| coercion.py | Core | Defensive numeric coercion utilities. Provides parse_float, parse_int, parse_timeout handling inf/nan/negative/non-numeric inputs. | ✅ |
| context_format.py | Core | Context formatting utilities. Unified management of document and context formatting logic with consi | ✅ |
| device_fingerprint.py | Legacy | Pure utility for device identification. Retained for migration only; superseded by encryption_key.py | ✅ |
| encryption_key.py | Core | Local-mode encryption key resolution: env var → file → auto-generate. Portable, no hardware binding | ✅ |
| document_utils.py | Core | Document object utilities. Provides LangChain Document front matter parsing, clean content extractio | ✅ |
| errors.py | Core | Framework-level error handling. ToolError exposes ``error_category`` from ``diagnostic_info`` for SSE/metrics; ``format_for_llm`` protocol. | ✅ |
| event_utils.py | Core | Provides dispatch_custom_event. | ✅ |
| files.py | Core | Pure file URL parsing utilities. No business logic dependencies. | ✅ |
| fuzzy_match.py | Core | Generic fuzzy matching module. 8-strategy progressive chain (+Unicode preprocessing + escape-drift  + closest-line hint) for LLM-generated code variations. | ✅ |
| hash_utils.py | Core | Unified hash utilities. High-performance document content hashing with multiple strategies (md5, sha | ✅ |
| image_utils.py | Core | Central media processing utilities (image/video/audio). Used by context_management, MediaFilterProcessor, and stream recovery to prevent overflow and multimodal rejection errors. | ✅ |
| log_rotation.py | Core | Agent utilities layer, used by audit logging and any growing log files. | ✅ |
| logger_utils.py | Core | Unified logging utilities. Provides consistent log format and convenience methods (step/success/erro | ✅ |
| locale.py | Core | BCP-47 locale normalization and Chinese detection (LocaleResolver SSOT) | ✅ |
| response_locale.py | Core | Agent output locale/formality suffix from engine_params.response_locale_policy | ✅ |
| lru_cache.py | Core | LRU cache utility. OrderedDict-based LRU cache implementation with TTL support. | ✅ |
| mime_types.py | Core | Centralized image MIME type utilities: extension ↔ MIME mappings and magic-bytes detection (detect_image_mime, extension_for_mime). | ✅ |
| network.py | Core | Pure network utilities. Get local IP using UDP socket (no actual data sent). | ✅ |
| progress_sink.py | Core | Progress event push mechanism. Tools implicitly obtain a sink via ContextVar to push intermediate pr | ✅ |
| rwlock.py | Core | General-purpose read-write lock concurrency primitive for multi-reader single-writer scenarios. | ✅ |
| text_cleaner.py | Core | Text cleaning utilities. Removes noise and irrelevant information from content to improve quality. | ✅ |
| text_sanitizer.py | Core | LLM streaming output sanitizer. Three-layer filtering ensures clean, garble-free text for user displ | ✅ |
| text_utils.py | Core | Text processing utilities. Provides token counting, language detection, smart truncation, and output | ✅ |
| tool_dynamic_hints.py | Core | LangChain tool `with_dynamic_hints` decorator — shared by agent and toolkits without cross-layer imports. | ✅ |
| token_estimation.py | Core | Message-level + bind-tools context token estimation for compress/summarize/budget and Turn1 inventory SSOT | ✅ |
| tree_truncator.py | Core | Tree Truncator (Smart Budget-Aware Truncation). Intelligently truncates tree structures (HTML/ARIA) to fit within token budgets while preserving structure. | ✅ |
| os_compat.py | Core | Cross-platform process groups (`get_process_group_kwargs`, `kill_process_group`, `terminate_process_graceful`) and file locks. | ✅ |
| url_utils.py | Core | Web and URL utilities. Provides URL normalization, parsing, cleanup, and type determination function | ✅ |

Workspace file enumeration lives in `toolkits/filesystem_suggest/indexer.py` (SSOT for `@` suggest and browse search).

| Submodule | Description |
|-----------|-------------|
| crypto/ | Config encryption utilities. |
| db/ | Database utilities for SQLite migration management. |
| media/ | Media utilities for image/video compression. |
| runtime/ | Agent run() lifecycle control parameters. All based on ContextVar for request-level isolation. |
| token_economics/ | LLM call full-chain economic metrics: token usage tracking (7 token types), cost calculation, and bu |

## Key Dependencies

- `langchain_core` — message types, document types, runnables (used by chat_utils, token_estimation, context_format, etc.)
