"""Honeytoken trap and streaming exfiltration detection for sandbox egress.

[INPUT]
- secrets::token_hex (POS: Python 随机数标准库)
- re::re (POS: 正则表达式标准库)
- logging::logging (POS: Python 日志标准库)

[OUTPUT]
- HoneytokenTrap: Manages polymorphic decoy credentials (AWS, OpenAI, GitHub, DB keys)
- StreamingHoneytokenScanner: Sliding-window scanner detecting canary tokens in byte streams
- HoneytokenExfiltrationBlockedError: Raised when canary token exfiltration is detected
- get_global_honeytoken_trap: Process-scoped singleton accessor

[POS]
Harness core security egress layer. Provides zero-prompt-overhead honeytoken traps.
Decoys are mounted as sandbox environment variables or mock vault entries, keeping
system prompt static (100% Prompt Cache intact) and terminating exfiltration at the proxy boundary.
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import Final

logger: logging.Logger = logging.getLogger(__name__)

# Standard canary prefix and identifier markers
HONEYTOKEN_MAGIC_PREFIX: Final[str] = "MYRM_CANARY_"
_DEFAULT_ENTROPY_BYTES: Final[int] = 16
_MAX_WINDOW_BYTES: Final[int] = 256


class HoneytokenExfiltrationBlockedError(Exception):
    """Raised when an outbound connection attempts to exfiltrate a honeytoken decoy."""

    def __init__(self, token_name: str, host: str, port: int, reason: str) -> None:
        self.token_name: str = token_name
        self.host: str = host
        self.port: int = port
        self.reason: str = reason
        super().__init__(
            f"Prompt injection exfiltration blocked: honeytoken '{token_name}' detected in outbound "
            f"traffic to {host}:{port} - {reason}"
        )

    def format_for_user(self) -> str:
        """Format an actionable diagnostic message for UI and audit logs."""
        return (
            f"Blocked unauthorized credential exfiltration to '{self.host}:{self.port}'. "
            f"Detected decoy honeytoken '{self.token_name}'. "
            "An untrusted source may have attempted an indirect prompt injection attack."
        )


class HoneytokenTrap:
    """Manages polymorphic canary credentials and performs zero-overhead leak detection."""

    def __init__(self) -> None:
        # Maps token string value to human-readable decoy name
        self._tokens_to_name: dict[str, str] = {}
        self._bytes_tokens_to_name: dict[bytes, str] = {}
        # Precompiled regex for fast multi-token scanning in text
        self._regex_pattern: re.Pattern[str] | None = None
        self._regex_pattern_bytes: re.Pattern[bytes] | None = None

    def register_token(self, token: str, name: str) -> None:
        """Register a decoy credential token into the active detection set."""
        clean_token = token.strip()
        if not clean_token or len(clean_token) < 8:
            return
        self._tokens_to_name[clean_token] = name
        self._bytes_tokens_to_name[clean_token.encode("utf-8")] = name
        self._recompile_patterns()

    def unregister_token(self, token: str) -> bool:
        """Remove a decoy credential from active detection."""
        clean_token = token.strip()
        removed = self._tokens_to_name.pop(clean_token, None) is not None
        self._bytes_tokens_to_name.pop(clean_token.encode("utf-8"), None)
        if removed:
            self._recompile_patterns()
        return removed

    def _recompile_patterns(self) -> None:
        """Recompile regex pattern for atomic multi-token scanning."""
        if not self._tokens_to_name:
            self._regex_pattern = None
            self._regex_pattern_bytes = None
            return

        sorted_tokens = sorted(self._tokens_to_name.keys(), key=len, reverse=True)
        escaped_str = "|".join(re.escape(t) for t in sorted_tokens)
        self._regex_pattern = re.compile(f"(?:{escaped_str})")

        sorted_bytes = sorted(self._bytes_tokens_to_name.keys(), key=len, reverse=True)
        escaped_bytes = b"|".join(re.escape(b) for b in sorted_bytes)
        self._regex_pattern_bytes = re.compile(rb"(?:" + escaped_bytes + rb")")

    def generate_sandbox_canaries(self, session_id: str = "") -> dict[str, str]:
        """Generate polymorphic high-entropy honeytoken environment variables.

        These credentials appear authentic to an adversarial LLM or inspecting script
        inside the sandbox, but carry no real authorization and trigger immediate
        network termination upon any outbound transmission.
        """
        sid = session_id[:8] if session_id else secrets.token_hex(4)
        entropy = secrets.token_hex(_DEFAULT_ENTROPY_BYTES).upper()

        aws_key = f"AKIA{sid.upper()}{entropy[:12]}TRAP"
        openai_key = f"sk-proj-canary-{sid}-{secrets.token_hex(20)}"
        github_token = f"ghp_canary_{sid}_{secrets.token_hex(18)}"
        db_pass = f"MyrmDecoyP@ss_{sid}_{entropy[:8]}"

        canaries: dict[str, str] = {
            "AWS_SECRET_ACCESS_KEY": aws_key,
            "OPENAI_API_KEY": openai_key,
            "GITHUB_TOKEN": github_token,
            "DATABASE_PASSWORD": db_pass,
        }

        for var_name, token_val in canaries.items():
            self.register_token(token_val, f"ENV:{var_name}")

        return canaries

    def scan_text(self, text: str) -> str | None:
        """Scan string content for any registered honeytoken.

        Returns:
            The matched honeytoken name, or None if clean.
        """
        if not text or self._regex_pattern is None:
            return None
        match = self._regex_pattern.search(text)
        if match:
            matched_str = match.group(0)
            return self._tokens_to_name.get(matched_str, "unknown_honeytoken")
        return None

    def scan_bytes(self, data: bytes) -> str | None:
        """Scan raw bytes for any registered honeytoken.

        Returns:
            The matched honeytoken name, or None if clean.
        """
        if not data or self._regex_pattern_bytes is None:
            return None
        match = self._regex_pattern_bytes.search(data)
        if match:
            matched_bytes = match.group(0)
            return self._bytes_tokens_to_name.get(matched_bytes, "unknown_honeytoken")
        return None

    def has_tokens(self) -> bool:
        """Return True if any honeytoken decoys are currently active."""
        return bool(self._tokens_to_name)


class StreamingHoneytokenScanner:
    """Sliding-window stream scanner for intercepting split honeytokens across TCP chunks."""

    def __init__(self, trap: HoneytokenTrap, max_window: int = _MAX_WINDOW_BYTES) -> None:
        self._trap: HoneytokenTrap = trap
        self._max_window: int = max_window
        self._buffer: bytes = b""

    def feed(self, chunk: bytes) -> str | None:
        """Feed incoming bytes and check if any honeytoken was completed.

        Returns:
            The matched honeytoken name if detected, else None.
        """
        if not chunk or not self._trap.has_tokens():
            return None

        self._buffer += chunk
        matched = self._trap.scan_bytes(self._buffer)
        if matched:
            return matched

        # Retain tail buffer to capture cross-chunk token splits
        if len(self._buffer) > self._max_window:
            self._buffer = self._buffer[-self._max_window :]

        return None

    def flush(self) -> str | None:
        """Flush final remaining bytes and scan for honeytokens."""
        if not self._buffer or not self._trap.has_tokens():
            return None
        matched = self._trap.scan_bytes(self._buffer)
        self._buffer = b""
        return matched


_GLOBAL_HONEYTOKEN_TRAP: HoneytokenTrap | None = None


def get_global_honeytoken_trap() -> HoneytokenTrap:
    """Get or initialize the process-scoped HoneytokenTrap singleton."""
    global _GLOBAL_HONEYTOKEN_TRAP
    if _GLOBAL_HONEYTOKEN_TRAP is None:
        _GLOBAL_HONEYTOKEN_TRAP = HoneytokenTrap()
    return _GLOBAL_HONEYTOKEN_TRAP
