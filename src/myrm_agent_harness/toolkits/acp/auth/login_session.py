"""Interactive subscription-login session for CLI agent backends.

Drives ``<cli> <login_args>`` as a child process and turns its console output into
a structured :class:`AuthEvent` stream the business layer can relay over SSE: login
URLs and device codes surface as actionable PROMPT events, progress lines as STATUS,
and the terminal outcome — verified against the on-disk credential — as SUCCESS or
ERROR. Backends whose login is not scriptable on this host yield a single PROMPT
directing the user to credential import.

[INPUT]
- toolkits.acp.auth._profiles::AuthProfile (POS: Authentication profile registry.)
- toolkits.acp.auth.credential_store::CredentialStore (POS: Credential persistence and detection.)
- utils.os_compat::get_process_group_kwargs, kill_process_group (POS: Cross-platform process group control.)

[OUTPUT]
- AuthEventType: Kinds of events emitted during a login session.
- AuthEvent: A single login progress/outcome event.
- CliLoginSession: Drives and observes an interactive CLI login.

[POS]
Interactive login session driver for the ACP auth subsystem.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import signal
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.toolkits.acp.auth._profiles import AuthProfile
from myrm_agent_harness.toolkits.acp.auth.credential_store import CredentialStore

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s'\"<>]+")
_CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")
_TERMINATE_GRACE_SECONDS = 5.0


class AuthEventType(StrEnum):
    """Kinds of events emitted during a login session."""

    STATUS = "status"  # progress / informational line
    PROMPT = "prompt"  # actionable: carries a login URL and/or device code for the user
    SUCCESS = "success"  # login completed and a credential was persisted
    ERROR = "error"  # login failed or produced no credential


@dataclass(frozen=True, slots=True)
class AuthEvent:
    """A single login progress or outcome event."""

    type: AuthEventType
    message: str
    url: str | None = None
    code: str | None = None


class CliLoginSession:
    """Drives an interactive CLI login and observes it to completion.

    Lifecycle: iterate :meth:`run` to receive the event stream; call :meth:`feed`
    to forward a user-supplied code to the CLI's stdin (for ``setup_token`` flows);
    call :meth:`cancel` to abort. A session instance drives a single login attempt.
    """

    def __init__(
        self,
        command: str,
        profile: AuthProfile,
        *,
        base_env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self._command = command
        self._profile = profile
        self._base_env: dict[str, str] = dict(base_env if base_env is not None else os.environ)
        self._cwd = cwd
        self._timeout = timeout_seconds
        self._process: asyncio.subprocess.Process | None = None
        self._store = CredentialStore(self._base_env)

    async def run(self) -> AsyncIterator[AuthEvent]:
        """Spawn the login command and stream login events to completion."""
        if not self._profile.scriptable_login:
            yield AuthEvent(
                AuthEventType.PROMPT,
                message=(
                    f"{self._profile.backend} login is not scriptable here. Sign in on a machine "
                    "with a browser, then import the credential file to finish."
                ),
            )
            return

        from myrm_agent_harness.utils.os_compat import get_process_group_kwargs

        args = [self._command, *self._profile.login_args]
        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._base_env,
                cwd=self._cwd,
                **get_process_group_kwargs(),
            )
        except (OSError, ValueError) as exc:
            yield AuthEvent(AuthEventType.ERROR, message=f"Failed to start login: {exc}")
            return

        yield AuthEvent(AuthEventType.STATUS, message=f"Starting {self._profile.backend} login…")

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        readers = [
            asyncio.create_task(_pump(self._process.stdout, queue)),
            asyncio.create_task(_pump(self._process.stderr, queue)),
        ]
        return_code: int | None = None
        try:
            async with asyncio.timeout(self._timeout):
                pending = len(readers)
                while pending > 0:
                    line = await queue.get()
                    if line is None:
                        pending -= 1
                        continue
                    event = self._classify(line)
                    if event is not None:
                        yield event
                return_code = await self._process.wait()
        except TimeoutError:
            await self._terminate()
            yield AuthEvent(AuthEventType.ERROR, message=f"Login timed out after {self._timeout}s")
            return
        finally:
            for task in readers:
                task.cancel()

        if self._store.is_authenticated(self._profile.backend):
            yield AuthEvent(AuthEventType.SUCCESS, message=f"{self._profile.backend} login complete")
        elif return_code == 0:
            yield AuthEvent(
                AuthEventType.ERROR,
                message="Login finished but no credential was persisted; try credential import.",
            )
        else:
            yield AuthEvent(AuthEventType.ERROR, message=f"Login exited with code {return_code}")

    async def feed(self, text: str) -> None:
        """Forward a user-supplied line (e.g. a pasted auth code) to the CLI's stdin."""
        proc = self._process
        if proc is None or proc.stdin is None or proc.stdin.is_closing():
            return
        try:
            proc.stdin.write((text.rstrip("\n") + "\n").encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("login_feed_failed backend=%s", self._profile.backend, exc_info=True)

    async def cancel(self) -> None:
        """Abort an in-progress login."""
        await self._terminate()

    def _classify(self, line: str) -> AuthEvent | None:
        """Map a console line to an AuthEvent, surfacing login URLs and device codes."""
        stripped = line.strip()
        if not stripped:
            return None
        url_match = _URL_RE.search(stripped)
        code_match = _CODE_RE.search(stripped)
        if url_match or code_match:
            url = url_match.group(0).rstrip(".,);]") if url_match else None
            return AuthEvent(
                AuthEventType.PROMPT,
                message=stripped,
                url=url,
                code=code_match.group(1) if code_match else None,
            )
        return AuthEvent(AuthEventType.STATUS, message=stripped)

    async def _terminate(self) -> None:
        """Terminate the login process group, escalating SIGTERM → SIGKILL."""
        proc = self._process
        if proc is None or proc.returncode is not None:
            return
        from myrm_agent_harness.utils.os_compat import kill_process_group

        pid = proc.pid
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if pid is not None:
                kill_process_group(pid, signal.SIGTERM)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_GRACE_SECONDS)
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if pid is not None:
                    kill_process_group(pid, signal.SIGKILL)


async def _pump(stream: asyncio.StreamReader | None, queue: asyncio.Queue[str | None]) -> None:
    """Forward decoded lines from a stream into ``queue``; enqueue ``None`` at EOF."""
    if stream is None:
        await queue.put(None)
        return
    try:
        async for raw in stream:
            await queue.put(raw.decode("utf-8", errors="replace").rstrip("\n"))
    finally:
        await queue.put(None)
