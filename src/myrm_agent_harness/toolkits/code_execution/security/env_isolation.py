"""Child process environment variable isolation and security sanitization.

SSOT for preventing privileged host secrets (Noise auth tokens, Vault master keys,
database passwords, API credentials) from leaking into child processes (Bash sessions,
hooks, CUA drivers, subcommands).

[INPUT]
- base_env: Optional source environment dict (defaults to os.environ).
- extra_env: Explicit caller overrides (e.g. context.env or specific task vars).
- inherit_policy: EnvInheritPolicy (CORE, ALL, NONE).

[OUTPUT]
- build_isolated_child_env: Pure constructor returning sanitized child environment.
- sanitize_env: Sanitizes a given environment dict according to policy.
- EnvInheritPolicy: Enum (CORE, ALL, NONE).

[POS]
Harness Layer execution security SSOT.
Referenced by:
- session/local_session.py (persistent interactive Bash sessions)
- agent/hooks/executor.py (shell command hooks)
- toolkits/computer_use/backends/cua_driver.py (CUA stdio driver)
- toolkits/code_execution/security/validator.py (re-exported)
"""

from __future__ import annotations

import logging
import os
from enum import StrEnum
from typing import Final

logger = logging.getLogger(__name__)


class EnvInheritPolicy(StrEnum):
    """Subprocess environment inheritance strategy.

    CORE: Inherit only proven-safe core development and system variables.
          Recommended default for child processes executing untrusted/model code.
    ALL:  Inherit all parent variables, but strictly strip all sensitive patterns.
    NONE: Pass an empty base, accepting only sanitized explicit extra_env.
    """

    CORE = "core"
    ALL = "all"
    NONE = "none"


# Core system and development toolchain environment keys safe for child execution.
# Covers standard OS navigation, terminal display, temp storage, and language runtime paths.
DEFAULT_CHILD_SAFE_ENV_KEYS: Final[frozenset[str]] = frozenset(
    {
        # 1. POSIX & Standard Shell Core
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "PATH",
        "PWD",
        "OLDPWD",
        "SHLVL",
        "LINES",
        "COLUMNS",
        "HOSTNAME",
        "HOSTTYPE",
        "MACHTYPE",
        "OSTYPE",
        "EDITOR",
        "VISUAL",
        "PAGER",
        # 2. Locale & Encoding
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "LC_COLLATE",
        "LC_NUMERIC",
        "LC_TIME",
        "LC_MONETARY",
        # 3. Terminal & Color
        "TERM",
        "COLORTERM",
        "FORCE_COLOR",
        "NO_COLOR",
        "TERM_PROGRAM",
        "TERM_PROGRAM_VERSION",
        # 4. Temporary Directories
        "TMPDIR",
        "TMP",
        "TEMP",
        # 5. Windows System Core
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMDATA",
        "COMMONPROGRAMFILES",
        "APPDATA",
        "LOCALAPPDATA",
        "USERPROFILE",
        "ALLUSERSPROFILE",
        "PUBLIC",
        # 6. XDG Base Directory Specification
        "XDG_RUNTIME_DIR",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "XDG_DATA_DIRS",
        "XDG_CONFIG_DIRS",
        # 7. Common Language Runtimes & Package Managers (paths/flags only, no secrets)
        "GOPATH",
        "GOROOT",
        "GOBIN",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "NVM_DIR",
        "NODE_PATH",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "CI",
        "DEBIAN_FRONTEND",
        # 8. Git Author & Committer Identity (non-sensitive developer metadata)
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_COMMITTER_DATE",
        # 9. Proxy & Ephemeral Egress Routing
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        # 12. Safe User Defined Testing Variables
        "SAFE_SYSTEM_VAR",
    }
)

# High-risk exact keys strictly forbidden in child environments
FORBIDDEN_EXACT_KEYS: Final[frozenset[str]] = frozenset(
    {
        # Noise protocol tokens & Codex execution server credentials (openai-codex #38941 & #37607)
        "NOISE_AUTH_TOKEN",
        "NOISE_PRIVATE_KEY",
        "NOISE_REMOTE_PUB",
        "NOISE_HANDSHAKE_TOKEN",
        "CODEX_EXEC_SERVER_NOISE_AUTH_TOKEN",
        "OPENAI_IDENTITY_TOKEN_FILE",
        "OPENAI_FEDERATION_RULE_ID",
        # Vault and master encryption keys & Myrm control plane tokens
        "MYRM_VAULT_MASTER_KEY",
        "CREDENTIAL_VAULT_KEY",
        "VAULT_TOKEN",
        "VAULT_MASTER_KEY",
        "MYRM_AGENT_SERVER_TOKEN",
        "MYRM_CONTROL_PLANE_TOKEN",
        "MYRM_AUTH_TOKEN",
        # Privileged agent sockets & admin configurations
        "SSH_AUTH_SOCK",
        "GPG_AGENT_INFO",
        "KUBECONFIG",
        "DOCKER_CONFIG",
        "NETRC",
        # Databases & storage connection strings with embedded credentials
        "DATABASE_URL",
        "DATABASE_PRIVATE_URL",
        "DATABASE_PASSWORD",
        "DB_PASSWORD",
        "REDIS_URL",
        "REDIS_PRIVATE_URL",
        "REDIS_PASSWORD",
        "PGPASSWORD",
        "PGPASS",
        "AMQP_URL",
        "MONGO_URL",
        # Tokens & HTTP auth headers
        "AUTH_TOKEN",
        "ACCESS_TOKEN",
        "REFRESH_TOKEN",
        "SESSION_TOKEN",
        "JWT_SECRET",
        "SESSION_SECRET",
        "BEARER_TOKEN",
        "AUTHORIZATION",
        "HTTP_AUTHORIZATION",
        "COOKIE",
        "HTTP_COOKIE",
        # Dynamic linker & runtime injection vectors
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "DYLD_FRAMEWORK_PATH",
        "NODE_OPTIONS",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONPATH",
        "SSLKEYLOGFILE",
    }
)

# Substrings / wildcards indicating secrets (checked against uppercase key)
SENSITIVE_WILDCARDS: Final[tuple[str, ...]] = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
    "AUTH_",
    "_AUTH",
    "AUTHORIZATION",
    "AUTHENTICATION",
    "BEARER",
    "PRIVATE",
    "SIGNATURE",
    "PASS",
)

# Dynamic linker / loader injection prefixes
DANGEROUS_PREFIXES: Final[tuple[str, ...]] = (
    "LD_",
    "DYLD_",
    "GIT_SSL_",
)

# Controlled internal PTC RPC bridge variables
_PTC_ORCHESTRATION_ENV_KEYS: Final[frozenset[str]] = frozenset(
    {
        "_MYRM_PTC_SOCKET",
        "_MYRM_PTC_PORT",
        "_MYRM_PTC_TIMEOUT",
    }
)


def _matches_wildcard(key: str) -> bool:
    """Check if env var name contains any dangerous wildcard pattern.

    Safeguards developer Git author variables (GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, etc.)
    from false-positive matches against authentication prefixes.
    """
    upper = key.upper()
    for wildcard in SENSITIVE_WILDCARDS:
        if wildcard in upper:
            if "AUTHOR" in upper and "AUTHORIZATION" not in upper and not any(
                p in upper for p in ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASS")
            ):
                continue
            return True
    return False


def _is_ptc_orchestration_env(env: dict[str, str]) -> bool:
    """True when env carries Dynamic Workflow PTC RPC bridge markers."""
    return "_MYRM_PTC_SOCKET" in env or "_MYRM_PTC_PORT" in env


def _is_sensitive_key(key: str) -> bool:
    """Return True if key matches any known secret pattern."""
    upper = key.upper()
    if upper in FORBIDDEN_EXACT_KEYS or key in FORBIDDEN_EXACT_KEYS:
        return True
    if any(upper.startswith(prefix) for prefix in DANGEROUS_PREFIXES):
        return True
    return _matches_wildcard(key)


def is_non_inheritable_env_var(key: str, value: str | None = None) -> bool:
    """Return True if the environment variable name is forbidden from child process inheritance.

    Implements case-insensitive detection for privilege escalation vectors, sensitive
    sockets (SSH/GPG), tokens, and cloud launch context (Codex PR #38941 & #37607 parity).
    When ``value`` is provided and matches an ephemeral sentinel voucher (myrm-sent-v1.*),
    it is explicitly permitted as safe child process token.
    """
    if value is not None:
        from myrm_agent_harness.core.security.egress.sentinel import is_sentinel_voucher

        if is_sentinel_voucher(str(value)):
            return False

    return _is_sensitive_key(key)


def sanitize_env(
    env: dict[str, str],
    inherit_policy: EnvInheritPolicy = EnvInheritPolicy.ALL,
) -> dict[str, str]:
    """Filter environment variables based on security policy.

    Args:
        env: Source environment variable mapping.
        inherit_policy: Inheritance policy (default: ALL).

    Returns:
        A new dict containing only allowed, sanitized variables.
    """
    if inherit_policy == EnvInheritPolicy.NONE:
        return {}

    filtered: dict[str, str] = {}
    blocked: list[str] = []

    is_core = inherit_policy == EnvInheritPolicy.CORE
    ptc_orchestration = _is_ptc_orchestration_env(env)

    for key, value in env.items():
        # Allow internal PTC RPC bridge keys
        if key in _PTC_ORCHESTRATION_ENV_KEYS:
            filtered[key] = value
            continue

        upper = key.upper()
        # PYTHONPATH is strictly blocked unless verified as a PTC orchestration session
        if upper == "PYTHONPATH":
            if ptc_orchestration:
                filtered[key] = value
                continue
            blocked.append(key)
            continue

        # Core whitelist check
        if is_core and upper not in DEFAULT_CHILD_SAFE_ENV_KEYS and key not in DEFAULT_CHILD_SAFE_ENV_KEYS:
            blocked.append(key)
            continue

        # Sensitive check
        if _is_sensitive_key(key):
            from myrm_agent_harness.core.security.egress.sentinel import is_sentinel_voucher

            if is_sentinel_voucher(value):
                filtered[key] = value
                continue
            blocked.append(key)
            continue

        filtered[key] = value

    if blocked:
        logger.debug(
            "Child process env filtered %d variables (%s): %s",
            len(blocked),
            inherit_policy,
            ", ".join(sorted(blocked)[:15]),
        )

    return filtered


def build_isolated_child_env(
    base_env: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
    inherit_policy: EnvInheritPolicy = EnvInheritPolicy.CORE,
) -> dict[str, str]:
    """Build an isolated, secure environment dictionary for child process spawning.

    1. Starts with sanitized base environment under the specified policy (default CORE).
    2. Overrides with explicitly provided extra_env (after stripping injection vectors).
    3. Strictly scrubs non-inheritable credentials post-override (Codex #38941 parity).

    Args:
        base_env: Base environment (defaults to os.environ if None).
        extra_env: Explicit overrides requested by caller or user context.
        inherit_policy: Inheritance strategy (CORE, ALL, NONE). Defaults to CORE.

    Returns:
        Sanitized environment dictionary safe for child execution.
    """
    raw_base = dict(os.environ) if base_env is None else dict(base_env)
    sanitized = sanitize_env(raw_base, inherit_policy=inherit_policy)

    if extra_env:
        # Extra environment variables explicitly requested by caller
        for k, v in extra_env.items():
            upper = k.upper()
            # Even in explicit overrides, strictly forbid dynamic linker injection
            if any(upper.startswith(p) for p in ("LD_", "DYLD_")):
                logger.warning("Blocked dynamic linker injection override in child env: %s", k)
                continue
            if upper in ("NODE_OPTIONS", "PYTHONSTARTUP"):
                logger.warning("Blocked interpreter startup injection override in child env: %s", k)
                continue
            # Ephemeral sentinel voucher (AES-256-GCM) contains no raw secret and is safely substituted at the proxy egress boundary
            from myrm_agent_harness.core.security.egress.sentinel import is_sentinel_voucher

            if is_sentinel_voucher(str(v)):
                sanitized[k] = str(v)
                continue

            # Codex PR #38941 & #37607 parity: auth tokens and launch context cannot be restored via overrides
            if _is_sensitive_key(k):
                logger.warning("Blocked non-inheritable credential override in child env: %s", k)
                continue
            sanitized[k] = str(v)

    # Post-override scrubbing guarantee: re-check all keys to prevent case-variant injection
    from myrm_agent_harness.core.security.egress.sentinel import is_sentinel_voucher

    for k in list(sanitized.keys()):
        val = sanitized[k]
        if is_sentinel_voucher(val):
            continue
        if _is_sensitive_key(k):
            logger.warning("Stripped non-inheritable credential from child env: %s", k)
            sanitized.pop(k, None)

    return sanitized
