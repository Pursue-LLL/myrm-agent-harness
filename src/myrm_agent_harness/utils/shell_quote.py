"""Cross-platform shell argument quoting and command escaping.

[INPUT]
None (pure stdlib: re, shlex, sys)

[OUTPUT]
- posix_shell_quote: POSIX shlex.quote wrapper with empty-string and control-character safety.
- windows_cmd_quote: Windows cmd.exe quoting compliant with CommandLineToArgvW, ^ metacharacter escape, and %% variable expansion prevention.
- windows_powershell_quote: PowerShell single-quote escaping.
- shell_quote: Unified facade dynamically dispatching to the host OS (or explicit target platform).

[POS]
Universal cross-platform shell argument escaping.
Protects subprocess invocations, PTC stubs, CLI launchers, and terminal execution from
argument injection, whitespace truncation, and Windows cmd.exe metacharacter/variable expansion.
"""

from __future__ import annotations

import re
import shlex
import sys
from typing import Literal

PlatformFlavor = Literal["posix", "windows", "powershell", "auto"]

_SAFE_POSIX_RE = re.compile(r"^[a-zA-Z0-9_./@=-]+$")
_SAFE_WINDOWS_RE = re.compile(r"^[a-zA-Z0-9_./\\:-]+$")
_CMD_META_CHARS_RE = re.compile(r"([()\]\[%!^\"`<>&|;, *?])")


def posix_shell_quote(arg: str) -> str:
    """Escape an argument for POSIX shells (bash/sh/zsh).

    - Empty string -> "''"
    - Safe tokens -> verbatim (protects KV-Cache / Prompt Cache)
    - Tokens with spaces/symbols -> single-quoted via shlex.quote
    """
    if not arg:
        return "''"
    if _SAFE_POSIX_RE.match(arg):
        return arg
    return shlex.quote(arg)


def windows_cmd_quote(
    arg: str,
    escape_cmd_metachars: bool = False,
    force_quote: bool = False,
) -> str:
    """Escape an argument for Windows cmd.exe / CommandLineToArgvW.

    Follows the Microsoft CommandLineToArgvW parsing standard:
    1. Fast-path: safe tokens without whitespace or quotes remain untouched (unless force_quote=True).
    2. Backslashes preceding a double quote or at the end of the argument are doubled.
    3. Double quotes are escaped with a preceding backslash.
    4. The entire argument is enclosed in double quotes.
    5. When escape_cmd_metachars=True (e.g. running in interactive batch scripts),
       cmd.exe metacharacters are caret-escaped (^).
    """
    if not arg:
        return '""'

    # Fast-path for simple safe tokens without spaces or quotes
    if (
        not force_quote
        and _SAFE_WINDOWS_RE.match(arg)
        and not any(c in arg for c in " \t\"")
    ):
        return arg

    # 1. Normalize line endings to avoid multiline cmd.exe breakages
    sanitized = arg.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")

    # 2. CommandLineToArgvW escaping:
    # Double backslashes before a quote: (\+)" -> \1\1\"
    out = re.sub(r'(\\*)(")', r'\1\1\\\2', sanitized)
    # Double backslashes at the end: (\+)$ -> \1\1
    out = re.sub(r"(\\+)$", r"\1\1", out)
    # Wrap in outer double quotes
    out = f'"{out}"'

    # 3. cmd.exe metacharacters caret escape if requested
    if escape_cmd_metachars:
        out = _CMD_META_CHARS_RE.sub(r"^\1", out)

    return out


def windows_powershell_quote(arg: str) -> str:
    """Escape an argument for Windows PowerShell.

    PowerShell treats single-quoted strings verbatim; inner single quotes are doubled.
    """
    if not arg:
        return "''"
    if _SAFE_POSIX_RE.match(arg):
        return arg
    escaped = arg.replace("'", "''")
    return f"'{escaped}'"


def shell_quote(arg: str, platform: PlatformFlavor = "auto") -> str:
    """Unified cross-platform argument quoting facade.

    Args:
        arg: String argument to quote.
        platform: Target platform flavor ('auto', 'posix', 'windows', 'powershell').
                  When 'auto', automatically detects host OS via sys.platform.

    Returns:
        Safely escaped string ready for command interpolation.
    """
    target = platform
    if target == "auto":
        target = "windows" if sys.platform == "win32" else "posix"

    if target == "windows":
        return windows_cmd_quote(arg)
    if target == "powershell":
        return windows_powershell_quote(arg)
    return posix_shell_quote(arg)
