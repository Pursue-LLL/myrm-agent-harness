# browser/doctor/

## Overview

Browser Doctor — pre-flight diagnostics and health checks. Validates dependencies,
configuration, environment, and browser launchability before actual operations,
with clear fix suggestions per failure. Includes precise orphan process detection
(patchright/playwright cache path matching) with dry-run-first cleanup safety.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade. Re-exports all symbols from `checks`/`orphans`/`report`/`auto_install` so `toolkits.browser.doctor` remains a single import point (incl. private symbols for backward-compatible imports) | ✅ |
| `checks.py` | Core | Environment and dependency checks: patchright/camoufox/browser executable/memory/disk/proxy/launch/extension relay + `run_doctor` orchestrator | ✅ |
| `orphans.py` | Core | Orphan automation process detection (chromium/driver), cleanup with safety dry-run, and `check_orphan_processes` | ✅ |
| `report.py` | Core | Report data model (`CheckStatus`/`DoctorCheckResult`/`DoctorReport`) and colored CLI rendering (`format_report`) | ✅ |
| `auto_install.py` | Core | Chromium auto-install via patchright CLI (`_try_auto_install_chromium`), triggered when launch check fails with a missing executable | ✅ |

## Key Dependencies

- `patchright` (browser automation library, optional extra `[browser]`)
- `psutil` (system monitoring, optional)
- `toolkits/browser/pool/browser_launcher::_get_install_env` (auto-install environment)
- `toolkits/browser/utils::is_timeout_error` (builtin/patchright timeout detection)
