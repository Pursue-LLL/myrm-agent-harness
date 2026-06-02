# pool/

## Overview
Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero-copy page reuse,

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero- | ✅ |
| browser_launcher.py | Core | Dedicated to browser instance launching, including: | ✅ |
| browser_pool.py | Core | Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing: | ✅ |
| circuit_breaker.py | Core | Circuit breaker module. Prevents persistently failing domains from degrading the entire system. | ✅ |
| config.py | Config | Browser pool configuration module. Public presets: `BrowserConfig.minimal()` / `standard()` / `defen | ✅ |
| context_factory.py | Core | Dedicated to BrowserContext creation and configuration, including: | ✅ |
| crash_watchdog.py | Core | Provides automatic crash recovery for GlobalBrowserPool: | ✅ |
| emulation.py | Core | Browser environment emulation configuration with type safety and parameter validation. | ✅ |
| memory_guard.py | Core | Memory monitoring module. Checks system memory usage at configured intervals; rejects new Page on th | ✅ |
| page_pool.py | Core | Page object pool. Implements zero-copy reset via CDP commands (clears cookies, storage, network stat | ✅ |
| proxy.py | Core | Manages proxy rotation across Browser Pool and CrawlEngine. Supports: | — |
| singleton.py | Core | Manages the GlobalBrowserPool singleton lifecycle, including atexit/SIGTERM cleanup hooks | ✅ |
| stealth.py | Core | Stealth anti-detection script loader. | ✅ |
| throttle.py | Core | Throttle strategy module. Defines the throttle protocol and two implementations, supports domain-lev | ✅ |
