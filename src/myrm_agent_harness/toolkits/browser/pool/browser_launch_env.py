"""Environment handed to the browser processes the launcher starts.

[INPUT]
- myrm_agent_harness.toolkits.code_execution.security.validator::sanitize_env (POS: host environment secret filter)
- ..process_owner::owner_stamp_env (POS: ownership stamp naming the launching process)

[OUTPUT]
- chromium_launch_env: sanitized host environment plus the ownership stamp, for Patchright Chromium
- camoufox_launch_env: sanitized host environment plus the fingerprint keys, for Camoufox

[POS]
Single place where a launched browser's environment is built, so no engine inherits the host's
secrets by accident and the Chromium process always carries the stamp the orphan check reads.
"""

from __future__ import annotations

import os

from ..process_owner import owner_stamp_env


def chromium_launch_env() -> dict[str, str]:
    """Host environment without secrets, stamped with the launching process as the owner."""
    from myrm_agent_harness.toolkits.code_execution.security.validator import sanitize_env

    return {**sanitize_env(os.environ.copy()), **owner_stamp_env()}


def camoufox_launch_env(fingerprint_env: object | None) -> dict[str, str]:
    """Host environment without secrets, overlaid with the string-valued fingerprint keys."""
    from myrm_agent_harness.toolkits.code_execution.security.validator import sanitize_env

    merged = sanitize_env(os.environ.copy())
    if isinstance(fingerprint_env, dict):
        for key, value in fingerprint_env.items():
            if isinstance(key, str) and isinstance(value, str):
                merged[key] = value
    return merged
