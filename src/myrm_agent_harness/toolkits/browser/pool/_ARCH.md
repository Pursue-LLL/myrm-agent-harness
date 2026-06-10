# pool/

## Overview
Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero-copy page reuse,

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero- | ✅ |
| browser_launcher.py | Core | Browser instance launching with CDP connect, intelligent retry, and zero-config Chromium auto-install for desktop users. | ✅ |
| browser_pool.py | Core | Global browser resource pool. Smart scheduling; wires PagePool.preserve_session from BrowserInstance.is_managed. DNS leak prevention when proxy_pool active. | ✅ |
| circuit_breaker.py | Core | Circuit breaker module. Prevents persistently failing domains from degrading the entire system. | ✅ |
| config.py | Config | Browser pool configuration module. Public presets: `BrowserConfig.minimal()` / `standard()` / `defensive()`. `ResourceBlockConfig` supports image/stylesheet/script/font/media type blocking + ad/tracker domain blocking. LaunchMode: LAUNCH/CONNECT/AUTO/REMOTE/EXTENSION. | ✅ |
| extension_bridge.py | Core | Extension Bridge Protocol for browser extension CDP proxy integration. Defines ExtensionBridge Protocol, ExtensionTab, ExtensionStatus, ExtensionBridgeNotAvailable. Framework-level contract for business layer implementation. | ✅ |
| context_factory.py | Core | BrowserContext creation/configuration. Installs resource blocking (incl. ad domains) independently of domain allowlist. Domain security (CSP/hardening) when allowlist present. | ✅ |
| crash_watchdog.py | Core | Provides automatic crash recovery for GlobalBrowserPool: | ✅ |
| emulation.py | Core | Browser environment emulation configuration with type safety and parameter validation. | ✅ |
| memory_guard.py | Core | Memory monitoring module. Checks system memory usage at configured intervals; rejects new Page on th | ✅ |
| page_pool.py | Core | Page object pool. Zero-copy reset for managed browsers; session-preserving reset for external CDP Chrome (no global cookie wipe). | ✅ |
| proxy.py | Core | Manages proxy rotation across Browser Pool and CrawlEngine. Supports: | — |
| singleton.py | Core | GlobalBrowserPool singleton lifecycle (atexit/SIGTERM hooks); pool startup sweeps orphan automation via `find_orphan_automation_processes` | ✅ |
| stealth.py | Core | Stealth anti-detection script loader. | ✅ |
| throttle.py | Core | Throttle strategy module. Defines the throttle protocol and two implementations, supports domain-lev | ✅ |
