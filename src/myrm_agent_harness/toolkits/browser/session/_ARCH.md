# session/

## Overview
Browser session components.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Browser session components. | — |
| browser_session.py | Core | Browser session aggregate root: snapshot/interact/navigate, `_publish_inspector_view`→`browser_view_update` SSE, stats. MRO: ViewMixin first, then Network before Navigation before Lifecycle. | ✅ |
| browser_session_view_mixin.py | Core | Browser Live Co-View SSE mixin: `_publish_inspector_view` with 300ms throttle via progress_sink. | ✅ |
| view_update_payload.py | Core | Shared browser inspector payload builder for SSE + REST (`capture_browser_view_update_data`, `build_browser_view_update_data`). | ✅ |
| browser_session_navigation_mixin.py | Core | Navigation, tab switching, private-network extension routing (`navigate_to_url` + capability guard), CAPTCHA coordination, Stealth Ladder auto-upgrade (Patchright→Camoufox), HTTP 403/429 fallthrough to CAPTCHA after proxy retries, engine affinity clear on terminal challenge / Camoufox launch failure (`ToolError`), site-experience injection | ✅ |
| browser_session_lifecycle_mixin.py | Core | Restart/close, component initialization, SessionVault auto-save on close | ✅ |
| browser_session_network_mixin.py | Core | Console log and network log/detail/replay APIs | ✅ |
| browser_session_extraction_mixin.py | Core | Content extraction, vision fallback, media URLs, screenshot compare/export mixin for BrowserSession. | ✅ |
| browser_session_page_mixin.py | Core | Viewport, dialog, and misc page-level helpers for BrowserSession (incl. `get_active_page` public facade). | ✅ |
| consent_dismisser.py | Core | Cookie consent auto-dismisser. 7-phase strategy: CMP-specific buttons (75+ selectors), generic attributes, multilingual text matching (14 languages), Shadow DOM CMPs, CMP JS APIs (Didomi/Cookiebot/Osano/Klaro), force-remove CMP containers (55+ selectors + iframe cleanup), scroll restoration. Also hooked into Navigator for L2 web_fetch coverage. Zero LLM cost, ~50ms. | ✅ |
| dialog_manager.py | Core | JavaScript dialog lifecycle manager (alert/confirm/prompt/beforeunload) with DialogPolicy strategies | ✅ |
| browser_session_persistence_mixin.py | Core | Encrypted session save/restore API for BrowserSession. | ✅ |
| browser_session_recording_mixin.py | Core | Playwright trace and HAR recording controls for BrowserSession. | ✅ |
| download_manager.py | Core | Browser file download manager. Single responsibility: listen for, process, and record file downloads | ✅ |
| extractor.py | Core | Content extraction manager. Text extraction (DOM→Markdown with SVG text/tspan support), screenshot capture (JPEG compression), screenshot comparison (fast dHash / accurate Canvas API), PDF export (with metadata header/footer and background preservation), visual content detection (Canvas/SVG significance check), media extraction (images/videos/audio direct URLs with intelligent filtering). | ✅ |
| humanize.py | Core | Humanized interaction helpers. Delay calculation (uniform for FAST, Gaussian for DEFAULT/CAREFUL), cubic Bézier mouse trajectory generation (ease-in-out, wobble, burst pauses, overshoot), and wheel-burst scroll humanization (`wheel_burst`/`scroll_notch_delta`/`scroll_burst_break_ms`/`scroll_phase_steps`: small wheel-input bursts with inertia-like gaps, config-driven accel/cruise/decel notch rhythm, burst-group pauses + occasional reading pause in CAREFUL mode). All pauses use `asyncio.sleep` so the humanize stack emits no CDP wait commands. | ✅ |
| interactor.py | Core | Element interaction manager. 15 ref-based action types (click/dblclick/type/fill/fill_credential/press/hover/focus/select/scroll/scroll_to_bottom/upload_file/drag/check/uncheck) + 7 coordinate-based actions (click/dblclick/type/press/hover/scroll/drag via interact_at). fill_credential resolves secrets via `core/security/credential_vault`. Includes ref resolution, self-healing, SPA wait, viewport bounds validation, and ref-not-found diagnosis with context sampling. Scrolling is humanized wheel-input: cursor targeted at the scroll container (element bounding box, clamped into viewport), then `wheel_burst` inertial delivery; `scroll_to_bottom` adds progress detection (scrollTop advance + scrollHeight growth), early exit when the container has no scrollable overflow (`height ≤ client + 1`), nested scroll-container resolution via `elementFromPoint` (only real wheel-scrollable boxes count — overflow auto/scroll or the document, skipping overflow:visible boxes), one retarget-on-stuck pass, and honest completed/stuck/max_reached status. `scroll`/coordinate `scroll` return honest outcome messages via `_scroll_with_report` (before/after measurement + settle re-check, no-op classified as no-overflow / already-at-edge / blocked). Humanized interaction via HumanizeConfig: Gaussian delay distribution (DEFAULT/CAREFUL) + Bézier mouse trajectory with wobble and overshoot (CAREFUL), shared by both ref and coordinate modes. | ✅ |
| network_logger.py | Core | Network request logging for the browser toolkit. Provides self-diagnosis capability for browser sessions; POST body preview redacted before truncation. | ✅ |
| network_intelligence.py | Core | CDP-based network intelligence for on-demand API response body retrieval and request replay. Raw POST body window stored for replay; get_summary redacts it before display; response body redacted before truncation (boundary-crossing credentials stay masked). | ✅ |
| console_logger.py | Core | Browser console log capture (JS errors/warnings/logs + page errors). Mirrors NetworkLogger lifecycle; raw text redacted before display truncation. | ✅ |
| page_analyzer.py | Core | Lightweight page structure analyzer. Executes fast DOM analysis via page.evaluate(), | ✅ |
| session_persistence.py | Core | Encrypted session persistence (save/restore/list/delete). Uses normalize_cookies + add_init_script from checkpoint.session_state | ✅ |
| session_lifecycle_hook.py | Protocol | SessionLifecycleHookProtocol: optional observer for session save/delete/expire events. | ✅ |
| session_memory_bridge.py | Core | SessionMemoryBridge: keeps active_browser_sessions profile attribute in sync with the vault via SessionLifecycleHookProtocol. | ✅ |
| snapshot_diff.py | Core | ARIA snapshottext'ssemantic diff(ref prefixnormalizeafterlinelevelfor). | ✅ |
| snapshot_manager.py | Core | Snapshot generation manager. Responsibilities: | ✅ |
| snapshot_result.py | Core | Immutable snapshot result type for browser ARIA snapshots. | ✅ |
| snapshot_suggestion.py | Core | Heuristic token / scope suggestions for large ARIA snapshots. | ✅ |
| tab_controller.py | Core | Tab lifecycle manager. Responsibilities: create/close tabs, switch active tab, LRU eviction, automatic popup capture (window.open / OAuth / target=_blank) with parent-child tracking and close auto-recovery, origin-based tab routing (find_tab_by_origin), domain-aware tab listing (list_tabs_with_info). | ✅ |
| vision_verifier.py | Core | 3-Layer Vision Verifier for Action-Verification Fusion. | ✅ |
| structured_extractor.py | Core | LLM-based structured data extraction using JSON Schema → Pydantic validation. Raw JSON fallback extracts answer via `extract_answer_text` (兼容 reasoning 模型 content 空回退) and parses via `parse_llm_json_list`/`parse_llm_json_object` selected by the schema top-level type (`expect_array`), so object schemas containing array fields are never misread as the embedded array. Robust against fences, prose, bare control chars, trailing commas. | ✅ |

## Key Dependencies

- `core`
