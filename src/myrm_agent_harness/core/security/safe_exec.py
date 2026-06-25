"""Safe command execution — direct exec by default, shell fallback when needed.

Part of the 5-layer onion security architecture (Layer 2 enhancement).
Works alongside shell_command_analyzer to provide defense-in-depth.

Execution strategy:
1. Classify command via ``needs_shell()`` based on shell metacharacter presence
2. DIRECT: ``shlex.split()`` + ``create_subprocess_exec`` (no shell interpreter)
3. SHELL: ``create_subprocess_shell`` (only when shell syntax is genuinely needed)

Security guarantees:
- DIRECT mode structurally eliminates $IFS, glob expansion, command substitution
- SHELL mode still protected by shell_command_analyzer (called by caller)
- Process group isolation (``start_new_session``) prevents orphan processes
- Timeout kills entire process tree via ``os.killpg(SIGKILL)``

[INPUT]
- types::user_credentials_ctx (POS: Security type definitions — ContextVar for user-affinity credentials)

[OUTPUT]
- ExecResult: structured execution result with mode audit field
- needs_shell(): pure predicate for shell metacharacter detection
- safe_exec(): unified async execution entry point

[POS]
Layer 2 enhancement. Called from:
- cron/runners.py — ShellJobRunner (primary consumer)
- Any future non-interactive command execution path
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from myrm_agent_harness.core.security.types import EphemeralUserCredential

logger = logging.getLogger(__name__)

_SHELL_METACHARACTERS: frozenset[str] = frozenset("|&;<>()$`*?[#~{}")


def needs_shell(command: str) -> bool:
    """Determine whether *command* requires a shell interpreter.

    Conservative strategy: any POSIX shell metacharacter triggers shell mode.
    This ensures command semantics are never broken by mis-classification.

    Quotes (``'``, ``"``) and backslash (``\\``) are intentionally excluded
    because ``shlex.split()`` handles them correctly in direct-exec mode.
    """
    return any(c in _SHELL_METACHARACTERS for c in command)


@dataclass(frozen=True, slots=True)
class ExecResult:
    """Immutable execution result with audit trail."""

    stdout: str
    stderr: str
    returncode: int
    mode: Literal["direct", "shell"]


def credential_env_overrides(
    credentials: tuple[EphemeralUserCredential, ...],
    *,
    allowed_issuers: list[str] | None = None,
) -> dict[str, str]:
    """Map EphemeralUserCredential issuers to process env vars (post-sanitize injection)."""
    overrides: dict[str, str] = {}
    normalized_allowed: set[str] | None = None
    if allowed_issuers is not None:
        normalized_allowed = {issuer.lower() for issuer in allowed_issuers}

    for cred in credentials:
        if normalized_allowed is not None and cred.issuer.lower() not in normalized_allowed:
            continue
        if cred.issuer == "feishu":
            overrides["FEISHU_USER_ACCESS_TOKEN"] = cred.token
        elif cred.issuer == "dingtalk":
            overrides["DINGTALK_USER_ACCESS_TOKEN"] = cred.token
        elif cred.issuer == "github":
            overrides["GITHUB_TOKEN"] = cred.token
        elif cred.issuer == "google_workspace":
            overrides["GOOGLE_WORKSPACE_TOKEN"] = cred.token
        else:
            overrides[f"{cred.issuer.upper()}_TOKEN"] = cred.token
    return overrides


def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the process and its entire process group (best-effort).

    Requires the process to have been started with os_compat.get_process_group_kwargs().
    """
    pid = proc.pid
    if pid is None:
        return
    from myrm_agent_harness.utils.os_compat import kill_process_group

    kill_process_group(pid, signal.SIGKILL)


async def safe_exec(
    command: str,
    *,
    timeout: int = 120,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    allowed_issuers: list[str] | None = None,
) -> ExecResult:
    """Execute *command* safely — direct exec preferred, shell fallback when needed.

    Process lifecycle:
    - Each subprocess runs in its own process group (``start_new_session``)
    - On timeout the entire process tree is killed via SIGKILL
    - Callers receive ``asyncio.TimeoutError`` after cleanup completes

    Raises:
        asyncio.TimeoutError: when execution exceeds *timeout* seconds.
        OSError: when the target binary cannot be found (direct mode).
    """
    use_shell = needs_shell(command)
    argv: list[str] = []

    if not use_shell:
        try:
            argv = shlex.split(command)
        except ValueError:
            logger.warning(
                "safe_exec: shlex.split failed, falling back to SHELL: %s",
                command[:120],
            )
            use_shell = True
        else:
            if not argv:
                return ExecResult(stdout="", stderr="empty command", returncode=1, mode="direct")

    from myrm_agent_harness.utils.os_compat import get_process_group_kwargs

    session_kwargs = get_process_group_kwargs()

    active_env = dict(env) if env is not None else dict(os.environ)
    from myrm_agent_harness.core.security.types import user_credentials_ctx

    try:
        credentials = user_credentials_ctx.get()
        active_env.update(credential_env_overrides(credentials, allowed_issuers=allowed_issuers))
    except LookupError:
        pass

    if use_shell:
        logger.warning("safe_exec SHELL mode: %s", command[:120])
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=active_env,
            **session_kwargs,
        )
        mode: Literal["direct", "shell"] = "shell"
    else:
        logger.warning("safe_exec DIRECT mode: %s", argv)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=active_env,
            **session_kwargs,
        )
        mode = "direct"

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        _kill_process_tree(proc)
        raise

    return ExecResult(
        stdout=stdout_bytes.decode(errors="replace").strip() if stdout_bytes else "",
        stderr=stderr_bytes.decode(errors="replace").strip() if stderr_bytes else "",
        returncode=proc.returncode or 0,
        mode=mode,
    )
