# pool/

## Overview
Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero-copy page reuse,

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero- | ✅ |
| browser_launcher.py | Core | Browser instance launching with CDP connect, intelligent retry, DevToolsActivePort discovery, and zero-config Chromium auto-install for desktop users. AUTO mode: discover local Chrome → probe → connect → fallback to launch. Camoufox fingerprint persistence: generates full config via `camoufox.utils.launch_options()`, saves to disk on first launch, and reloads via `from_options` for consistent device identity. Self-healing: corrupted fingerprint JSON is auto-deleted and regenerated. | ✅ |
| chrome_discovery.py | Core | Local Chromium-based browser discovery via DevToolsActivePort files. Scans Chrome/Edge/Chromium/Brave/Canary data dirs across macOS/Linux/Windows. 4-phase: file scan → HTTP probe → TCP fallback → fixed port 9222. | ✅ |
| browser_pool.py | Core | Global browser resource pool. Smart scheduling; wires PagePool.preserve_session from BrowserInstance.is_managed. DNS leak prevention when proxy_pool active. Anti-throttling/anti-focus Chrome args for headful mode. Auto-resolves Camoufox fingerprint directory (`$MYRM_DATA_DIR` or `$CWD/.myrm/browser_fingerprints`). | ✅ |
| circuit_breaker.py | Core | Circuit breaker module. Prevents persistently failing domains from degrading the entire system. | ✅ |
| config.py | Config | Browser pool configuration module. Public presets: `BrowserConfig.minimal()` / `standard()` / `defensive()`. `ResourceBlockConfig` supports image/stylesheet/script/font/media type blocking + ad/tracker domain blocking. LaunchMode: LAUNCH/CONNECT/AUTO/REMOTE/EXTENSION. `HumanizeConfig` provides three humanization levels (FAST/DEFAULT/CAREFUL) for interaction anti-detection: Gaussian delay distribution and Bézier mouse trajectory. | ✅ |
| extension_bridge.py | Core | Extension Bridge Protocol for browser extension CDP proxy integration. Defines ExtensionBridge Protocol, ExtensionTab, ExtensionStatus, ExtensionBridgeNotAvailable. Framework-level contract for business layer implementation. | ✅ |
| context_factory.py | Core | BrowserContext creation/configuration. Syncs Accept-Language with EmulationConfig.locale. Installs resource blocking (incl. ad domains) independently of domain allowlist. Domain security (CSP/hardening) when allowlist present. | ✅ |
| crash_watchdog.py | Core | Provides automatic crash recovery for GlobalBrowserPool: | ✅ |
| emulation.py | Core | Browser environment emulation configuration with type safety and parameter validation. | ✅ |
| memory_guard.py | Core | Memory monitoring module. Checks system memory usage at configured intervals; rejects new Page on th | ✅ |
| page_pool.py | Core | Page object pool. Zero-copy reset for managed browsers; session-preserving reset for external CDP Chrome (no global cookie wipe). | ✅ |
| proxy.py | Core | Manages proxy rotation across Browser Pool and CrawlEngine. Supports: | — |
| singleton.py | Core | GlobalBrowserPool singleton lifecycle (atexit/SIGTERM hooks); pool startup sweeps orphan automation via `find_orphan_automation_processes` | ✅ |
| stealth.py | Core | Stealth anti-detection script loader. | ✅ |
| throttle.py | Core | Throttle strategy module. Defines the throttle protocol and two implementations, supports domain-lev | ✅ |
| engine_affinity.py | Core | Domain-level engine affinity memory. Remembers which BrowserEngine succeeded for a domain (e.g. after Chromium→CAMOUFOX upgrade) so subsequent sessions skip the probe-and-upgrade cycle. Module-level singleton via `get_engine_affinity_store()`. In-memory LRU + JSON file persistence with TTL. | ✅ |
