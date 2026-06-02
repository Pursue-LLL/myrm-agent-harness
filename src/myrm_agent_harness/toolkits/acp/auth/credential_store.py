"""Detect, import, and clear subscription login state for CLI agent backends.

Pure, environment-aware filesystem operations against the per-backend credential
files declared in :mod:`._profiles`. Detection powers pre-flight auth checks and
status badges; import is the universal fallback when scripted login is unavailable
or inconvenient (the user pastes an ``auth.json`` captured on another machine).

[INPUT]
- toolkits.acp.auth._profiles::AuthProfile, profile_for (POS: Authentication profile registry.)

[OUTPUT]
- AuthStatus: Authentication state of a backend.
- CredentialState: Resolved auth state with the satisfying credential path.
- CredentialStore: Detect / import / clear subscription credentials.

[POS]
Credential persistence and detection layer for the ACP auth subsystem.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.toolkits.acp.auth._profiles import profile_for

logger = logging.getLogger(__name__)

_MAX_CREDENTIAL_BYTES = 256 * 1024  # generous ceiling; real auth.json files are < 8 KB


class AuthStatus(StrEnum):
    """Authentication state of a backend."""

    AUTHENTICATED = "authenticated"  # a non-empty credential file is present
    NOT_AUTHENTICATED = "not_authenticated"  # profile known, but no credential found
    UNKNOWN = "unknown"  # no auth profile registered for this backend


@dataclass(frozen=True, slots=True)
class CredentialState:
    """Resolved authentication state for a single backend."""

    backend: str
    status: AuthStatus
    credential_path: str | None = None  # the file that satisfied the check, if any
    detail: str = ""

    @property
    def authenticated(self) -> bool:
        return self.status is AuthStatus.AUTHENTICATED


class CredentialStore:
    """Detect, import, and clear CLI subscription credentials.

    Constructed with an environment snapshot so the control plane can relocate a
    CLI's home (e.g. ``CODEX_HOME`` → a persistent volume) and have detection,
    import, and clearing all target the same location transparently.
    """

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env: dict[str, str] = dict(env if env is not None else os.environ)

    def state(self, backend: str) -> CredentialState:
        """Resolve the current authentication state of a backend."""
        profile = profile_for(backend)
        if profile is None:
            return CredentialState(backend=backend, status=AuthStatus.UNKNOWN, detail="no auth profile")

        for path in profile.resolve_credential_paths(self._env):
            if _has_credential(path):
                return CredentialState(
                    backend=profile.backend,
                    status=AuthStatus.AUTHENTICATED,
                    credential_path=str(path),
                )
        return CredentialState(
            backend=profile.backend,
            status=AuthStatus.NOT_AUTHENTICATED,
            detail="no credential file found",
        )

    def is_authenticated(self, backend: str) -> bool:
        """Whether a non-empty subscription credential is present for the backend."""
        return self.state(backend).authenticated

    def import_credential(
        self,
        backend: str,
        content: str,
        *,
        filename: str | None = None,
    ) -> CredentialState:
        """Persist a user-supplied credential blob to the backend's credential file.

        The universal fallback for subscription auth: the user logs in on a machine
        where they have a browser, copies the resulting credential file, and pastes
        it here. Written atomically with owner-only permissions.

        Raises:
            ValueError: unknown backend, empty/oversized content, or invalid filename.
        """
        profile = profile_for(backend)
        if profile is None:
            msg = f"No auth profile for backend {backend!r}"
            raise ValueError(msg)

        blob = content.strip()
        if not blob:
            msg = "Credential content is empty"
            raise ValueError(msg)
        if len(blob.encode("utf-8")) > _MAX_CREDENTIAL_BYTES:
            msg = f"Credential content exceeds {_MAX_CREDENTIAL_BYTES} bytes"
            raise ValueError(msg)

        target_name = filename or profile.credential_files[0]
        if target_name in {".", ".."} or "/" in target_name or "\\" in target_name:
            msg = f"Invalid credential filename {target_name!r}"
            raise ValueError(msg)
        if target_name.endswith(".json"):
            _validate_json(blob)

        target = profile.resolve_home(self._env) / target_name
        _atomic_write_secure(target, blob)
        logger.info("credential_imported backend=%s path=%s bytes=%d", profile.backend, target, len(blob))
        return CredentialState(
            backend=profile.backend,
            status=AuthStatus.AUTHENTICATED,
            credential_path=str(target),
        )

    def clear(self, backend: str) -> CredentialState:
        """Remove all known credential files for a backend (logout)."""
        profile = profile_for(backend)
        if profile is None:
            msg = f"No auth profile for backend {backend!r}"
            raise ValueError(msg)
        removed = 0
        for path in profile.resolve_credential_paths(self._env):
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                continue
            except OSError:
                logger.warning("credential_clear_failed backend=%s path=%s", profile.backend, path, exc_info=True)
        logger.info("credential_cleared backend=%s removed=%d", profile.backend, removed)
        return CredentialState(backend=profile.backend, status=AuthStatus.NOT_AUTHENTICATED)


def _has_credential(path: Path) -> bool:
    """Whether a path is an existing, non-empty regular file."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _validate_json(blob: str) -> None:
    """Ensure a credential blob destined for a ``.json`` file parses."""
    try:
        json.loads(blob)
    except json.JSONDecodeError as exc:
        msg = f"Credential content is not valid JSON: {exc}"
        raise ValueError(msg) from exc


def _atomic_write_secure(target: Path, content: str) -> None:
    """Write ``content`` to ``target`` atomically with owner-only permissions."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        logger.debug("chmod_dir_failed path=%s", target.parent, exc_info=True)

    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".cred-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
