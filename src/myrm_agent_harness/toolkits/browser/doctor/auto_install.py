"""Browser Doctor — Chromium auto-install fallback.

Attempts to install Chromium via the patchright CLI when the doctor launch
check detects a missing browser executable.
"""

from __future__ import annotations

import logging

from .report import CheckStatus, DoctorCheckResult

logger = logging.getLogger(__name__)


async def _try_auto_install_chromium() -> DoctorCheckResult | None:
    """Attempt to auto-install Chromium via patchright CLI.

    Returns a DoctorCheckResult on success/failure, or None if the patchright
    CLI is not available.
    """
    import asyncio
    import shutil

    if not shutil.which("patchright"):
        return DoctorCheckResult(
            name="auto_install",
            status=CheckStatus.ERROR,
            message="'patchright' CLI not found — cannot auto-install Chromium",
            fix="pip install patchright && patchright install chromium",
        )

    from ..pool.browser_launcher import _get_install_env

    install_timeout = 600  # 10 minutes
    logger.info(
        "Doctor auto_fix: installing Chromium via 'patchright install chromium'..."
    )
    try:
        env = _get_install_env()
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "patchright",
                "install",
                "chromium",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            ),
            timeout=install_timeout,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=install_timeout
        )

        if proc.returncode == 0:
            return DoctorCheckResult(
                name="auto_install",
                status=CheckStatus.OK,
                message="Chromium auto-installed successfully",
                details={"output": (stdout or b"").decode(errors="replace")[:300]},
            )
        return DoctorCheckResult(
            name="auto_install",
            status=CheckStatus.ERROR,
            message=f"Chromium auto-install failed (exit {proc.returncode})",
            fix="Run 'patchright install chromium' manually",
            details={"stderr": (stderr or b"").decode(errors="replace")[:300]},
        )
    except TimeoutError:
        return DoctorCheckResult(
            name="auto_install",
            status=CheckStatus.ERROR,
            message="Chromium auto-install timed out (10 minutes)",
            fix="Check network connection and disk space, then run 'patchright install chromium' manually",
        )
    except Exception as exc:
        return DoctorCheckResult(
            name="auto_install",
            status=CheckStatus.ERROR,
            message=f"Chromium auto-install failed: {exc}",
            fix="Run 'patchright install chromium' manually",
        )
