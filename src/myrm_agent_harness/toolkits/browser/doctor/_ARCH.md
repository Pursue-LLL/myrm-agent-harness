# browser/doctor/

## Overview

Browser Doctor — pre-flight diagnostics and health checks. Validates dependencies,
configuration, environment, and browser launchability before actual operations,
with clear fix suggestions per failure. Includes leftover process detection (a browser
process is a leftover when the process that launched it, read from its ownership stamp, is gone and the process itself is a Chromium binary)
with dry-run-first cleanup safety.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade. Re-exports the public symbols of `checks`/`launch_check`/`orphan_check`/`orphans`/`sandboxes`/`report` so `toolkits.browser.doctor` remains a single import point; private helpers are imported from their defining module | ✅ |
| `checks.py` | Core | Environment and dependency checks: patchright/camoufox/memory/disk/proxy + `run_doctor` orchestrator (which also schedules the launch test, the orphan scan and host-supplied `extra_checks`, so a host application can add checks that depend on itself, e.g. a server's browser extension relay, without the framework knowing that host; a host check that raises becomes one warning row, a name that collides with a built-in check is rejected). `check_memory`/`check_disk` are public because the runtime doctor reuses them. The disk check probes the volume of `tempfile.gettempdir()`, the directory the browser really writes to. The camoufox check reports whether the browser build is installed (package + build via `pool/camoufox_availability`, no launch attempted), not mere importability. Engine versions come from distribution metadata, because neither package exposes a usable `__version__`; unreadable metadata is reported as `unknown` instead of aborting the report | ✅ |
| `launch_check.py` | Core | `check_browser_launch`: headless launch test with its own 20 s timeout; the probe browser carries the ownership stamp. Kept apart from the static checks because it is the only check that starts a browser process; releases the Playwright connection on every exit path and maps each failure class (patchright missing, timeout, executable not found, permission denied, other) to its own fix | ✅ |
| `orphan_check.py` | Core | `check_orphan_processes`: turns the orphan scan and the dry-run stale sandbox scan into one `DoctorCheckResult`, keeping `orphans` free of the report data model | ✅ |
| `orphans.py` | Core | `find_orphan_automation_processes`: stamped Chromium processes whose owner (pid + start time) is gone; unstamped, unreadable or malformed processes, stamped processes that are not Chromium (the stamp can reach an application a browser opens, so a process counts as Chromium only when its name, executable file name or `argv[0]` file name contains `chrom`) and the calling process are never reported. The scan and both re-checks share one judgement (`_is_leftover_process`). `cleanup_orphan_processes`: dry-run by default, re-verifies every pid right before signalling it (`not_an_orphan` otherwise), SIGTERM then, after the 3 s default grace period `timeout_s` (a headed Chrome whose driver died ignores SIGTERM), SIGKILL behind a second identity check; `killed` counts the leftovers gone when the call ends (a browser's helpers exit with its main process and are counted), `timeout_s=0` only signals. The scan reads `--user-data-dir` from the argument list, so profile paths with spaces stay whole. Typed result shapes (`OrphanProcess`/`OrphanCleanupResult`). Nothing in the library calls the cleanup on its own; hosts and the CLI decide when | ✅ |
| `sandboxes.py` | Core | `cleanup_stale_automation_sandboxes`: dry-run-first prune of stale automation sandboxes. A clone is skipped, in the preview and in the prune alike, while the browser app it belongs to is running (a live browser holds no file in its clone open, so liveness is read from the process table via the app's `CFBundleIdentifier`); an unreadable process table protects everything. Typed `SandboxCleanupResult` | ✅ |
| `report.py` | Core | Report data model (`CheckStatus`/`DoctorCheckResult`/`DoctorReport`) and colored CLI rendering (`format_report`) | ✅ |

## Key Dependencies

- `patchright` (browser automation library, optional extra `[browser]`)
- `toolkits/browser/pool/camoufox_availability::camoufox_unavailable_reason` (non-downloading Camoufox readiness probe)
- `psutil` (system monitoring, optional)
- `toolkits/browser/process_owner` (ownership stamp read by `orphans`, applied by `launch_check` to its probe browser)
- `toolkits/browser/utils::is_timeout_error` (builtin/patchright timeout detection)
