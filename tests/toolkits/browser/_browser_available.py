"""Reliable Chromium/Patchright availability detection for browser integration tests.

[INPUT]
- patchright.async_api (POS: Chromium automation runtime)
- patchright browsers registry (resolves the actual executable path)

[OUTPUT]
- chromium_available(): bool — True when patchright is installed AND its
  managed Chromium executable exists on disk.

[POS]
The legacy detection used ``shutil.which("chromium")`` / ``shutil.which("google-chrome")``,
which misses patchright-managed browsers (installed under the Playwright cache
directory, e.g. ``~/Library/Caches/ms-playwright`` or ``$PLAYWRIGHT_BROWSERS_PATH``)
and therefore skipped real-browser integration tests on macOS/Windows even when a
usable Chromium was present. ``chromium_available()`` resolves the executable via
the same registry the launch path uses, honoring ``PLAYWRIGHT_BROWSERS_PATH``,
and verifies the file actually exists.
"""

from __future__ import annotations

import contextlib
from functools import lru_cache


@lru_cache(maxsize=1)
def chromium_available() -> bool:
    """Return True when patchright is importable and its Chromium binary exists."""
    try:
        import asyncio

        from patchright.async_api import async_playwright
    except ImportError:
        return False

    async def _probe() -> bool:
        pw = None
        try:
            pw = await async_playwright().start()
            executable = pw.chromium.executable_path
            if not executable:
                return False
            from pathlib import Path

            return Path(executable).exists()
        except Exception:
            return False
        finally:
            if pw is not None:
                with_pw = pw
                with contextlib.suppress(Exception):
                    await with_pw.stop()

    try:
        return asyncio.run(_probe())
    except RuntimeError:
        # Event loop already running (e.g. called from an asyncio test) — fall
        # back to a best-effort filesystem probe of the Playwright cache dirs.
        from pathlib import Path

        candidates = (
            Path.home() / "Library/Caches/ms-playwright",
            Path.home() / ".cache/ms-playwright",
            Path.home() / "AppData/Local/ms-playwright",
        )
        return any(base.is_dir() and any(base.glob("chromium-*/chrome*")) for base in candidates)
