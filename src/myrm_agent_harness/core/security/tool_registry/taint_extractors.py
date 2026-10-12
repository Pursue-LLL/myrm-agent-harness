"""Taint-label extractors for tool arguments (URL, secret file, secret command).

[INPUT]
- (none — pure functions over tool-call argument dicts)

[OUTPUT]
- sanitize_url_for_taint / taint_url_from_args: scheme+host+path only, never query or fragment
- taint_secret_file_from_args: credential-file paths in file-tool arguments
- taint_secret_command_from_args: credential-file access inside shell command arguments

[POS]
Extractors wired into ``TOOL_SAFETY_METADATA`` as ``taint_extractor`` callbacks, so the
context taint tracker labels where a tool result came from without storing secrets.
"""

from __future__ import annotations

import re


def sanitize_url_for_taint(url: str | None) -> str | None:
    """Sanitize a URL to prevent leaking sensitive query parameters or hashes.

    Extracts only the scheme, netloc, and path.
    """
    if not url:
        return None
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        # Reconstruct without query (?) and fragment (#)
        sanitized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return sanitized
    except Exception:
        # If parsing fails, return a generic string rather than leaking the raw input
        return "invalid_or_redacted_url"


def taint_url_from_args(args: dict[str, object]) -> str | None:
    """Extract and sanitize the ``url`` arg for taint labeling (non-str values dropped)."""
    url = args.get("url")
    return sanitize_url_for_taint(url if isinstance(url, str) else None)


_SECRET_FILE_POSITIVE_RE = re.compile(
    r"(?:^|[/\\])(?:\.env(?:\.[a-zA-Z0-9_-]+)?|\.netrc|\.aws[/\\].*|\.ssh[/\\].*|"
    r"id_rsa(?:_[a-zA-Z0-9_-]+)?|id_ed25519|id_ecdsa|id_dsa|"
    r"credentials\.json|token\.txt|master\.key|service[_-]account\.json)(?:$|[?#])",
    re.IGNORECASE,
)

_SECRET_FILE_NEGATIVE_RE = re.compile(
    r"(?:\.example|\.sample|\.template|test_|mock|fixture|spec)",
    re.IGNORECASE,
)

_SECRET_CMD_POSITIVE_RE = re.compile(
    r"(?:\bcat\b|\bhead\b|\btail\b|\bless\b|\bmore\b|\bcp\b|\bmv\b|\bgrep\b|\bcurl\b|\bwget\b|\bpython\b|\bnode\b)"
    r"[\s\S]{1,60}"
    r"(?:~/\.(?:ssh|aws|kube)|\$HOME/\.(?:ssh|aws|kube)|\.env|id_rsa|id_ed25519|credentials\.json|master\.key)",
    re.IGNORECASE,
)


def taint_secret_file_from_args(args: dict[str, object]) -> str | None:
    """Extract secret credential path from tool arguments if matched."""
    for key in ("path", "file_path", "filepath", "target_file", "source_file", "filename"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            path_str = val.strip()
            if _SECRET_FILE_POSITIVE_RE.search(path_str) and not _SECRET_FILE_NEGATIVE_RE.search(path_str):
                return f"secret_file:{path_str}"
    return None


def taint_secret_command_from_args(args: dict[str, object]) -> str | None:
    """Extract secret file access from bash / shell command arguments."""
    for key in ("command", "cmd", "script"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            cmd_str = val.strip()
            if _SECRET_CMD_POSITIVE_RE.search(cmd_str) and not _SECRET_FILE_NEGATIVE_RE.search(cmd_str):
                snippet = cmd_str[:80] + ("..." if len(cmd_str) > 80 else "")
                return f"secret_cmd:{snippet}"
    return None
