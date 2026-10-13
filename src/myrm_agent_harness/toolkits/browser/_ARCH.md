# browser/

## Overview
Browser toolkit public entry point. Aggregates and exports the module's core API

Detailed design: [BROWSER_SYSTEM.md](BROWSER_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Browser toolkit public entry point. Aggregates and exports the module's core API | ✅ |
| __main__.py | Internal | CLI entry point for browser toolkit diagnostics. | ✅ |
| exceptions.py | Core | Exception hierarchy definition. `EngineUnavailableError` (a `BrowserLaunchError`) marks an engine switch refused before any session state changed. RefNotFoundError provides structured diagnostic info, including URL change suggestions; message + format_for_llm output are redacted at construction to keep query-string credentials out of LLM tool errors. | ✅ |
| observability.py | Core | Observability module for the browser toolkit. Provides video recording, progress notifications, checkpoint monitoring, BrowserRunTelemetry active compute and data transfer metrics, and 3-minute runaway watchdog. | ✅ |
| process_owner.py | Core | Ownership stamp `MYRM_BROWSER_OWNER=<pid>:<start_ms>` carried by every Chromium the toolkit launches (`owner_stamp_env` is merged into the browser's own launch env, never into the host process environment, so unrelated subprocesses cannot inherit it) and `read_owner_state`, which classifies any process as unstamped / owner alive / owner gone / unknown (unreadable or malformed stamps are never treated as leftovers; an environment read that raises psutil's macOS `SystemError` counts as unreadable). Start times are compared with the boot time removed on Linux, where psutil derives them from the wall clock, so a clock step never makes a live owner look gone. The stamp reaches whatever a browser starts, an application it opens included, so it proves who launched a process and not what it is. Stamped by `pool` and the doctor launch probe, judged by `doctor/orphans` (owner gone and a Chromium binary); `pool` and `orphans` do not import each other | ✅ |
| recording_manager.py | Core | Unified browser recording manager. Provides lifecycle management and file management | ✅ |
| url_routing.py | Core | URL routing for hybrid private/public network navigation. Detects private URLs for Extension Bridge fallback in sandbox mode. | ✅ |

| Submodule | Description |
|-----------|-------------|
| action_capture/ | DOM action recorder for the server Browser Skill Recording Wizard — captures click/fill/select/press/hover/navigate into ActionStep sequences via injected JS. |
| captcha/ | CAPTCHA detection and coordination subpackage. Provides Protocol-based pluggable solver architecture, HTML regex detector, asyncio.Event state machine coordinator, and default ManualSolver. Integrated into BrowserSession.navigate(). |
| checkpoint/ | Task-level checkpoint/resume module for the browser toolkit. Fully reuses LangGraph Checkpointer's p |
| decision_discipline/ | Next-step decision discipline rulebooks, pre-flight action guards, target selection validators, and single-key text output contracts. See [decision_discipline/_ARCH.md](decision_discipline/_ARCH.md). |
| diff/ | Screenshot diff utilities — unified comparison system. |
| doctor/ | Pre-flight diagnostics and health checks. Facade + checks/launch_check/orphan_check/orphans/sandboxes/report submodules. |
| domain_filter/ | Deep domain filtering, resource blocking, and ad/tracker domain blocking. Four-layer defense: CSP + route interception + JS hardening + CDP audit. `__init__.py` exposes DomainAllowlist/install_domain_filter; `ad_domains.py` lazily loads the bundled `assets/ad_domains.txt` (~3500 domains). |
| domain_skills/ | Domain executable skills — manifest-based Python tool registry for repeated-domain acceleration. Complements SiteExperienceStore (prompt-layer) with an executable layer. Includes builtin skill packs (e.g. x-com). |
| enhancers/ | DOM enhancers. Provides progressive enhancement (React/Vue/CDP) and SPA stabilization scripts. |
| navigation/ | Page navigation utility (Navigator) + Playwright document SSRF guard. `ssrf_guard.py` registers document-level route interception during goto with redirect-chain validation, aligned with OpenClaw policy. Non-timeout navigation failures are wrapped into BrowserNavigationError (intelligent diagnostics); SSRF blocks propagate unchanged. |
| pool/ | Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero- |
| session/ | Browser session components. |
| session_vault/ | AES-256-GCM encrypted session storage. `__init__.py` exposes SessionVault + entry/summary/metrics types + exception hierarchy; `backends/` holds pluggable storage backends (file/cloud protocol). |
| snapshot/ | Snapshot module. Provides comprehensive snapshot capabilities, ARIA tree enhancements, and O(1) Self-Healing Locators. |
| spaces/ | Browser task spaces. Manages BrowserTaskSpace entities with isolated BrowserContext, asyncio concurrency locks, and HarnessTaskSpaceManager. |
| tools/ | API layer of the browser toolkit. Maps BrowserSession capabilities to 8 LangChain @tool functions (incl. AST-gated execute_script), |
| utils/ | Shared utilities and constants (e.g., selectors, proxy error detection). |
| wait/ | Page wait strategies. `__init__.py` exposes wait_for_page_ready + WaitStrategy/WaitMetrics + global stats; `_impl.py` holds 4 strategy implementations, `_types.py` the type definitions, `_dom_stable_js.py` the DOM stability JS generator. |

## Key Dependencies

- `core/security/credential_vault` — `fill_credential` resolves password/TOTP by label (secrets never in LLM context)
- `core/security/guards/ssrf`, `core/security/audit`, `core/security/detection/content_boundary`
- Optional extra `[browser]`: `patchright`, `camoufox` (version floor pinned in `pyproject.toml`; the ~1.2 GB browser build is a separate manual install, see `pool/camoufox_availability.py`), `orjson` (`session_vault/__init__.py`, `session/session_persistence.py`)
