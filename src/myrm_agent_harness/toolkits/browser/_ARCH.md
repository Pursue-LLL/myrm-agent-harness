# browser/

## Overview
Browser toolkit public entry point. Aggregates and exports the module's core API

Detailed design: [BROWSER_SYSTEM.md](BROWSER_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Browser toolkit public entry point. Aggregates and exports the module's core API | ✅ |
| __main__.py | Internal | CLI entry point for browser toolkit diagnostics. | ✅ |
| _dom_stable_js.py | Internal | DOM stability detection JavaScript generator. | ✅ |
| _wait_impl.py | Internal | Concrete wait strategy implementations. Each strategy function receives a Page instance and paramete | ✅ |
| _wait_types.py | Internal | Wait strategy type definitions and runtime statistics module. | ✅ |
| doctor.py | Core | Browser diagnostics: patchright + camoufox dependency checks, launchability probes, orphan automation process detection (Chromium + driver node; patchright/playwright/puppeteer caches), safe cleanup (`cleanup_orphan_processes`), and auto-fix Chromium install with CDN mirror fallback. | ✅ |
| domain_filter.py | Core | Deep domain filtering, resource blocking, and ad/tracker domain blocking module. Four-layer defense: CSP + route interception + JS hardening + CDP audit. Route handler blocks ad domains (3500+ via ad_domains.py) and resource types. | ✅ |
| assets/ | Data | Bundled static files (`ad_domains.txt`). Shipped in wheel via `pyproject.toml` force-include. See [assets/_ARCH.md](assets/_ARCH.md). |
| ad_domains.py | Data | Lazy loader for bundled `assets/ad_domains.txt` (~3500 Peter Lowe ad/tracker domains). | ✅ |
| exceptions.py | Core | Exception hierarchy definition. RefNotFoundError provides structured diagnostic info, including URL  | ✅ |
| navigation.py | Core | Page navigation utility module. Responsibilities: Hybrid Session routing (fast HTTP injection for static pages), Page navigation, history, smart wait, and timeout fallback rescue (window.stop). Integrates proxy error detection and state-preserving auto-retry. | ✅ |
| navigation_ssrf_guard.py | Core | Playwright document navigation SSRF guard (route handler during goto + redirect chain validation). Aligns with OpenClaw document-level policy. | ✅ |
| observability.py | Core | Observability module for the browser toolkit. Provides video recording, progress notifications, and  | ✅ |
| recording_manager.py | Core | Unified browser recording manager. Provides lifecycle management and file management | ✅ |
| retry_policy.py | Core | Retry policy framework. Zero external dependencies. Async-first design. | ✅ |
| session_vault.py | Core | Encrypted session storage module for the browser toolkit. Called by BrowserSession's | ✅ |
| session_vault_exceptions.py | Core | Exception type definitions for SessionVault. Provides fine-grained error classification | ✅ |
| session_vault_types.py | Config | Data types for SessionVault module (SessionEntry, SessionSummary, VaultMetrics). | ✅ |
| url_routing.py | Core | URL routing for hybrid private/public network navigation. Detects private URLs for Extension Bridge fallback in sandbox mode. | ✅ |
| wait_strategies.py | Core | Page wait strategy module. Provides 5 wait strategies (including SPA_STABLE): | ✅ |

| Submodule | Description |
|-----------|-------------|
| backends/ | Storage backend abstraction layer for SessionVault. Defines interfaces via Protocol, |
| captcha/ | CAPTCHA detection and coordination subpackage. Provides Protocol-based pluggable solver architecture, HTML regex detector, asyncio.Event state machine coordinator, and default ManualSolver. Integrated into BrowserSession.navigate(). |
| checkpoint/ | Task-level checkpoint/resume module for the browser toolkit. Fully reuses LangGraph Checkpointer's p |
| diff/ | Screenshot diff utilities — unified comparison system. |
| enhancers/ | DOM enhancers. Provides progressive enhancement (React/Vue/CDP) and SPA stabilization scripts. |
| pool/ | Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero- |
| session/ | Browser session components. |
| snapshot/ | Snapshot module. Provides comprehensive snapshot capabilities, ARIA tree enhancements, and O(1) Self-Healing Locators. |
| tools/ | API layer of the browser toolkit. Maps BrowserSession capabilities to 7 LangChain @tool functions, |
| utils/ | Shared utilities and constants (e.g., selectors, proxy error detection). |

## Key Dependencies

- `core/security/credential_vault` — `fill_credential` resolves password/TOTP by label (secrets never in LLM context)
- `core/security/guards/ssrf`, `core/security/audit`, `core/security/detection/content_boundary`
- Optional extra `[browser]`: `patchright`, `camoufox>=0.4.11`, `orjson` (`session_vault.py`, `session/session_persistence.py`)
