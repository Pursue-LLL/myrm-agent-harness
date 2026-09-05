# browser/

## Overview
Browser toolkit public entry point. Aggregates and exports the module's core API

Detailed design: [BROWSER_SYSTEM.md](BROWSER_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Browser toolkit public entry point. Aggregates and exports the module's core API | ✅ |
| __main__.py | Internal | CLI entry point for browser toolkit diagnostics. | ✅ |
| exceptions.py | Core | Exception hierarchy definition. RefNotFoundError provides structured diagnostic info, including URL change suggestions; message + format_for_llm output are redacted at construction to keep query-string credentials out of LLM tool errors. | ✅ |
| observability.py | Core | Observability module for the browser toolkit. Provides video recording, progress notifications, checkpoint monitoring, BrowserRunTelemetry active compute and data transfer metrics, and 3-minute runaway watchdog. | ✅ |
| recording_manager.py | Core | Unified browser recording manager. Provides lifecycle management and file management | ✅ |
| url_routing.py | Core | URL routing for hybrid private/public network navigation. Detects private URLs for Extension Bridge fallback in sandbox mode. | ✅ |

| Submodule | Description |
|-----------|-------------|
| action_capture/ | DOM action recorder for the server Browser Skill Recording Wizard — captures click/fill/select/press/hover/navigate into ActionStep sequences via injected JS. |
| captcha/ | CAPTCHA detection and coordination subpackage. Provides Protocol-based pluggable solver architecture, HTML regex detector, asyncio.Event state machine coordinator, and default ManualSolver. Integrated into BrowserSession.navigate(). |
| checkpoint/ | Task-level checkpoint/resume module for the browser toolkit. Fully reuses LangGraph Checkpointer's p |
| diff/ | Screenshot diff utilities — unified comparison system. |
| doctor/ | Pre-flight diagnostics and health checks. Facade + checks/orphans/report submodules. |
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
- Optional extra `[browser]`: `patchright`, `camoufox>=0.4.11`, `orjson` (`session_vault/__init__.py`, `session/session_persistence.py`)
