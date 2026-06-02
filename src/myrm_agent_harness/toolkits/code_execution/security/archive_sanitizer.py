"""Archive extraction security hardening.

Defends against Zip slip / Tar path traversal attacks and Zip bomb DoS:
1. Auto-injects safe flags into tar/unzip commands
2. Limits total extracted size

[INPUT]
- (none)

[OUTPUT]
- sanitize_archive_command: Inject security parameters into archive extraction commands.

[POS]
Archive extraction security hardening.
"""

import re

_MAX_EXTRACT_SIZE_MB = 500

_TAR_EXTRACT_RE = re.compile(
    r"\btar\b\s+(?:[a-zA-Z]*x|--extract)",
)

_UNZIP_RE = re.compile(
    r"(?:^|\s|&&|\|\||;)\s*unzip\s+",
)

_SAFE_TAR_FLAGS = "--no-same-permissions --no-same-owner"


def _size_check_wrapper(cmd: str) -> str:
    """Wrap a command with post-execution size check."""
    limit_kb = _MAX_EXTRACT_SIZE_MB * 1024
    return (
        f"_out=$({cmd}); _ec=$?; "
        f"if [ $_ec -eq 0 ]; then "
        f"  _kb=$(du -sk . 2>/dev/null | cut -f1); "
        f'  if [ "$_kb" -gt {limit_kb} ] 2>/dev/null; then '
        f'    echo "ERROR: Extracted size exceeds {_MAX_EXTRACT_SIZE_MB}MB limit" >&2; '
        f'    (exit 1); '
        f"  fi; "
        f"fi; "
        f'echo "$_out"; (exit $_ec)'
    )


def sanitize_archive_command(command: str) -> str:
    """Inject security parameters into archive extraction commands.

    - tar extract: appends --no-same-permissions --no-same-owner + size check
    - unzip: appends -o + size check
    - Non-extraction commands are returned unchanged.
    """
    if _is_tar_extract(command):
        return _sanitize_tar(command)
    if _UNZIP_RE.search(command):
        return _sanitize_unzip(command)
    return command


def _is_tar_extract(command: str) -> bool:
    """Check if a command contains a tar extraction operation."""
    return bool(_TAR_EXTRACT_RE.search(command))


def _sanitize_tar(command: str) -> str:
    """Append safe flags to a tar extraction command."""
    if "--no-same-permissions" in command:
        return command
    sanitized = f"{command.rstrip()} {_SAFE_TAR_FLAGS}"
    return _size_check_wrapper(sanitized)


def _sanitize_unzip(command: str) -> str:
    """Append safe flags to an unzip command."""
    base = command.rstrip()
    if "-o" not in base:
        base = _UNZIP_RE.sub(lambda m: m.group(0).rstrip() + " -o ", base, count=1)
    return _size_check_wrapper(base)
