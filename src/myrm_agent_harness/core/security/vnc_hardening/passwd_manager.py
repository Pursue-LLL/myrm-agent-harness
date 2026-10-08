"""
[POS] src/myrm_agent_harness/core/security/vnc_hardening/passwd_manager.py
[INPUT] os, secrets, string, stat, pathlib, typing
[OUTPUT] VncSecurityException, VncPasswdManager
VNC credential and password manager enforcing rfbauth complexity and file permission sandboxing.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import os
import secrets
import stat
import string
from pathlib import Path

logger = logging.getLogger(__name__)


class VncSecurityError(Exception):
    """Exception raised when VNC security baseline is violated."""


class VncPasswdManager:
    """Manages VNC password generation, complexity evaluation, and credential file isolation."""

    @staticmethod
    def evaluate_password_strength(password: str) -> tuple[bool, str]:
        """Verify that password meets enterprise security standards.

        Standards:
        - Minimum length: 8 characters
        - Must contain at least one letter and at least one digit
        """
        if len(password) < 8:
            return False, "Password length must be at least 8 characters"

        has_letter = any(c.isalpha() for c in password)
        has_digit = any(c.isdigit() for c in password)

        if not (has_letter and has_digit):
            return False, "Password must contain both alphanumeric letters and digits"

        return True, "Password meets strength baseline"

    @staticmethod
    def generate_secure_password(length: int = 14) -> str:
        """Generate high-entropy random password suitable for VNC rfbauth."""
        alphabet = string.ascii_letters + string.digits
        # Ensure at least 1 letter and 1 digit
        pwd = [
            secrets.choice(string.ascii_letters),
            secrets.choice(string.digits),
        ]
        pwd += [secrets.choice(alphabet) for _ in range(max(6, length - 2))]
        # Shuffle for uniform distribution
        chars = list(pwd)
        secrets.SystemRandom().shuffle(chars)
        return "".join(chars)

    @staticmethod
    def inspect_and_harden_file_permissions(file_path: str | Path) -> tuple[bool, str]:
        """Inspect file permissions to ensure POSIX 0600 (owner read/write only).

        If permissions are too permissive, attempt to tighten to 0600.
        """
        path = Path(file_path)
        if not path.exists():
            return False, f"Password file '{path}' does not exist on disk"

        try:
            st = path.stat()
            current_mode = stat.S_IMODE(st.st_mode)
            # Owner rw only is 0o600
            if (current_mode & 0o077) != 0:
                logger.warning(
                    "Password file %s has insecure permissions %o. Auto-remediating to 0600.",
                    path,
                    current_mode,
                )
                try:
                    os.chmod(path, 0o600)
                    return True, f"Insecure permissions {oct(current_mode)} hardened to 0600"
                except OSError as err:
                    return (
                        False,
                        f"Failed to remediate file permissions from {oct(current_mode)} to 0600: {err}",
                    )
            return True, "File permissions compliant (0600)"
        except OSError as exc:
            return False, f"OS error inspecting file permissions: {exc}"
