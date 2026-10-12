"""Camoufox stealth-engine readiness probe.

Camoufox is an optional Firefox-based escalation engine. The Python package
alone is not enough: the ~1.2 GB browser build must also be present, and the
library's default resolver downloads it silently when missing. This module
answers "is a usable build installed right now?" without ever downloading, so
the launcher, session restart and Doctor all share one verdict and a missing
build fails fast instead of stalling a request on an implicit install. A build
that is installed but cannot start (for example missing system libraries) is
not detected here; the launch itself fails and the session rolls back.

[INPUT]
- camoufox (optional extra [browser]; imported lazily)
- ..exceptions::EngineUnavailableError (POS: engine refused before any state change)

[OUTPUT]
- CAMOUFOX_INSTALL_FIX: operator-facing install instructions (Doctor ``fix``)
- camoufox_unavailable_reason: ``None`` when a usable build is installed, else a short reason
- require_camoufox_ready: raise ``EngineUnavailableError`` unless a usable build is installed

[POS]
Non-downloading readiness probe for the optional Camoufox engine. Reasons are
deliberately free of filesystem paths and library internals because they reach
the agent through tool errors; operators get details from logs and Doctor.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ..exceptions import EngineUnavailableError

logger = logging.getLogger(__name__)

_EXECUTABLE_ENV = "CAMOUFOX_EXECUTABLE_PATH"

CAMOUFOX_INSTALL_FIX = (
    "Run 'camoufox fetch' once (about 1.2 GB download), or point "
    f"{_EXECUTABLE_ENV} at an existing Camoufox build for offline or sandboxed hosts"
)


def camoufox_unavailable_reason() -> str | None:
    """Return why no usable Camoufox build is installed, or ``None`` when there is one.

    Mirrors the launch-time resolution (``CAMOUFOX_EXECUTABLE_PATH`` first, then
    the installed build) but never triggers a download. Never raises.
    """
    try:
        from camoufox.exceptions import CamoufoxNotInstalled, UnsupportedVersion
        from camoufox.pkgman import camoufox_path, launch_path
    except ImportError:
        return "camoufox package is not installed"

    override = os.environ.get(_EXECUTABLE_ENV, "").strip()
    if override:
        if Path(override).is_file():
            return None
        return f"{_EXECUTABLE_ENV} does not point to an existing file"

    try:
        launch_path(camoufox_path(download_if_missing=False))
    except CamoufoxNotInstalled:
        return "Camoufox browser build is not installed"
    except UnsupportedVersion:
        return "installed Camoufox browser build is incompatible with the camoufox package"
    except Exception as exc:
        logger.debug("Camoufox readiness probe failed", exc_info=True)
        return f"Camoufox browser build could not be verified ({type(exc).__name__})"
    return None


def require_camoufox_ready() -> None:
    """Raise ``EngineUnavailableError`` unless a usable Camoufox build is installed."""
    reason = camoufox_unavailable_reason()
    if reason is not None:
        logger.warning("Camoufox stealth engine unavailable: %s. %s", reason, CAMOUFOX_INSTALL_FIX)
        raise EngineUnavailableError(reason)
