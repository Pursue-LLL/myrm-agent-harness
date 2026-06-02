"""PTC security constraints.

[INPUT]
- ptc.models::PtcConfig (POS: PTC configuration)

[OUTPUT]
- scrub_child_env: Remove dangerous environment variables
- TERMINAL_BLOCKED_PARAMS: Params forbidden in terminal calls from PTC
- SAFE_ENV_PREFIXES: Allowed env variable prefixes

[POS]
Security boundary for PTC execution. Prevents credential exfiltration,
resource abuse, and dangerous terminal parameters.
"""

from __future__ import annotations

import os
from typing import Final

SAFE_ENV_PREFIXES: Final[tuple[str, ...]] = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_",
    "TERM",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SHELL",
    "LOGNAME",
    "XDG_",
    "DISPLAY",
    "WAYLAND_DISPLAY",
)

SECRET_SUBSTRINGS: Final[tuple[str, ...]] = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "AUTH",
    "API_",
    "AWS_",
    "AZURE_",
    "GCP_",
    "OPENAI",
    "ANTHROPIC",
    "GOOGLE_",
    "MYRM_",
)

TERMINAL_BLOCKED_PARAMS: Final[frozenset[str]] = frozenset(
    {"background", "pty", "notify_on_complete", "watch_patterns"}
)


def scrub_child_env(parent_env: os._Environ[str] | dict[str, str]) -> dict[str, str]:
    """Build a minimal safe environment for the PTC child process.

    Removes API keys, tokens, and other sensitive variables while keeping
    essential system paths and locale settings.
    """
    result: dict[str, str] = {}

    for key, value in parent_env.items():
        upper_key = key.upper()

        if any(secret in upper_key for secret in SECRET_SUBSTRINGS):
            continue

        if any(upper_key.startswith(prefix) for prefix in SAFE_ENV_PREFIXES):
            result[key] = value

    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["PYTHONIOENCODING"] = "utf-8"
    result["PYTHONUTF8"] = "1"

    return result
