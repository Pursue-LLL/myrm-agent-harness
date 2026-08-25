"""MCP stdio environment variable security guard.

Provides:
- ``is_dangerous_env_key``: Checks if an environment variable key represents a high-risk
  injection vector (dynamic linker, runtime hooks, proxy, TLS bypass, package manager redirection,
  git command hijacking). Supports case-insensitive normalization and prefix/wildcard detection.
- ``sanitize_mcp_env``: Pure function that strips dangerous environment variables from a
  dictionary before subprocess spawning, returning the sanitized dictionary and list of blocked keys.

[INPUT]
- myrm_agent_harness.toolkits.code_execution.security.blacklist (POS: core dangerous env definitions)

[OUTPUT]
- is_dangerous_env_key: Check if a single environment variable key is dangerous
- sanitize_mcp_env: Filter dangerous environment variables from a dict

[POS]
MCP stdio security guard layer. Framework-level pure functions for environment variable sanitization.
"""

from __future__ import annotations

import logging
from typing import Final

from myrm_agent_harness.toolkits.code_execution.security.blacklist import (
    DANGEROUS_ENV_PREFIXES,
    DANGEROUS_ENV_VARS,
    DANGEROUS_ENV_WILDCARDS,
)

logger = logging.getLogger(__name__)

# Pre-normalized uppercase sets and tuples for fast O(1) case-insensitive lookup
_NORMALIZED_DANGEROUS_KEYS: Final[frozenset[str]] = frozenset(
    k.upper() for k in DANGEROUS_ENV_VARS
)

_NORMALIZED_DANGEROUS_PREFIXES: Final[tuple[str, ...]] = tuple(
    p.upper() for p in DANGEROUS_ENV_PREFIXES
)

_NORMALIZED_DANGEROUS_WILDCARDS: Final[tuple[str, ...]] = tuple(
    w.upper() for w in DANGEROUS_ENV_WILDCARDS
)

# Explicitly allowed spec-reserved variables that should never be blocked as false positives
_RESERVED_SPEC_VARS: Final[frozenset[str]] = frozenset({"PLUGIN_ROOT", "PLUGIN_DATA"})


def is_dangerous_env_key(key: str) -> tuple[bool, str]:
    """Check if an environment variable key is a known high-risk injection vector.

    Normalizes the key to uppercase to prevent case-obfuscation attacks across
    Linux, macOS, and Windows.

    Args:
        key: The environment variable name.

    Returns:
        A tuple of ``(is_dangerous, reason)``. If safe, returns ``(False, "")``.
    """
    if not key or not isinstance(key, str):
        return False, ""

    normalized = key.strip().upper()
    if not normalized:
        return False, ""

    # Never block spec-reserved plugin variables
    if normalized in _RESERVED_SPEC_VARS:
        return False, ""

    # 1. Exact match on known dangerous variables (linker, runtime hooks, proxy, git, etc.)
    if normalized in _NORMALIZED_DANGEROUS_KEYS:
        return True, f"Environment variable '{key}' is a prohibited high-risk system variable"

    # 2. Dangerous prefix match (e.g. LD_*, DYLD_*, GIT_SSL_*)
    for prefix in _NORMALIZED_DANGEROUS_PREFIXES:
        if normalized.startswith(prefix):
            return True, f"Environment variable '{key}' matches prohibited prefix '{prefix}'"

    # 3. Dangerous wildcard/token match for credential vault master keys or sensitive credentials
    if "VAULT_MASTER_KEY" in normalized:
        return True, f"Environment variable '{key}' targets sensitive master key"

    return False, ""


def sanitize_mcp_env(env: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Sanitize environment variables for MCP stdio process execution.

    Strips any variables that match dangerous linker, runtime hook, or hijacking patterns.

    Args:
        env: The raw environment variables dictionary.

    Returns:
        A tuple of ``(sanitized_env, blocked_keys)``.
    """
    if not env:
        return {}, []

    sanitized: dict[str, str] = {}
    blocked: list[str] = []

    for key, value in env.items():
        is_dangerous, reason = is_dangerous_env_key(key)
        if is_dangerous:
            blocked.append(key)
            logger.warning("[MCPStdioEnvGuard] Blocked dangerous env variable '%s': %s", key, reason)
        else:
            sanitized[key] = value

    return sanitized, blocked
