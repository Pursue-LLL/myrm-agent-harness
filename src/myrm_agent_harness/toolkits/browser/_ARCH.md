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
| doctor.py | Core | Browser toolkit diagnostics module. Validates dependencies, configuration, | ✅ |
| domain_filter.py | Core | Deep domain filtering and resource blocking module for the browser toolkit. Called by BrowserSession | ✅ |
| exceptions.py | Core | Exception hierarchy definition. RefNotFoundError provides structured diagnostic info, including URL  | ✅ |
| navigation.py | Core | Page navigation utility module. Responsibilities: Hybrid Session routing (fast HTTP injection for static pages), Page navigation, history, smart wait, and timeout fallback rescue (window.stop). Integrates proxy error detection and state-preserving auto-retry. | ✅ |
| observability.py | Core | Observability module for the browser toolkit. Provides video recording, progress notifications, and  | ✅ |
| recording_manager.py | Core | Unified browser recording manager. Provides lifecycle management and file management | ✅ |
| retry_policy.py | Core | Retry policy framework. Zero external dependencies. Async-first design. | ✅ |
| session_vault.py | Core | Encrypted session storage module for the browser toolkit. Called by BrowserSession's | ✅ |
| session_vault_exceptions.py | Core | Exception type definitions for SessionVault. Provides fine-grained error classification | ✅ |
| session_vault_types.py | Config | Data types for SessionVault module. | ✅ |
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

- `core`
- Optional extra `[browser]`: `patchright`, `orjson` (`session_vault.py`, `session/session_persistence.py`)
