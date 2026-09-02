"""Zero-leakage credential and sensitive value redaction for compliance audit trails.

[INPUT]
- types::AuditTrailEntry
- re, hashlib, typing

[OUTPUT]
- sanitize_sensitive_data: Recursively scrub strings/dicts of API keys, Bearer tokens, secrets
- compute_redaction_fingerprint: Generates a stable audit fingerprint for verified scrubbed reports

[POS]
Harness-level pure redaction engine ensuring zero credentials reach compliance archives.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization header Bearer token
    (re.compile(r"(?i)(bearer\s+)([a-zA-Z0-9_\-\.]{8,})"), r"\1"),
    # Generic API Keys / Tokens: api_key, token, password, secret, private_key with = / : / whitespace
    (re.compile(r"(?i)(api[_-]?key|token|password|secret|passwd|access[_-]?key|auth[_-]?key)\s*[:=\s]\s*['\"]?([a-zA-Z0-9_\-\.]{6,})['\"]?"), r"\1"),
    # OpenAI / Anthropic / GitHub token prefixes
    (re.compile(r"\b(sk-[a-zA-Z0-9_\-]{16,}|ghp_[a-zA-Z0-9]{20,}|gho_[a-zA-Z0-9]{20,}|xoxb-[a-zA-Z0-9_\-]{16,})\b"), ""),
]


def redact_string(val: str) -> str:
    """Scrub sensitive patterns from a single string value while preserving length fingerprint."""
    if not val:
        return val

    res = val
    for pattern, prefix_group in _SECRET_PATTERNS:
        matches = list(pattern.finditer(res))
        for match in reversed(matches):
            full_span = match.span()
            matched_text = match.group(0)
            length = len(matched_text)
            sha_fp = hashlib.sha256(matched_text.encode("utf-8")).hexdigest()[:8]
            replacement = f"[REDACTED:len={length}:fp={sha_fp}]"
            res = res[: full_span[0]] + replacement + res[full_span[1] :]

    return res


def sanitize_sensitive_data(obj: Any) -> Any:
    """Recursively scrub sensitive credential tokens from arbitrary Python structures."""
    if isinstance(obj, str):
        return redact_string(obj)
    if isinstance(obj, Mapping):
        sanitized_dict: dict[str, Any] = {}
        for k, v in obj.items():
            str_k = str(k)
            # If key name itself indicates a secret, mask value directly
            if any(term in str_k.lower() for term in ("secret", "token", "password", "key", "auth", "credential")):
                if isinstance(v, str):
                    length = len(v)
                    sha_fp = hashlib.sha256(v.encode("utf-8")).hexdigest()[:8]
                    sanitized_dict[str_k] = f"[REDACTED:len={length}:fp={sha_fp}]"
                else:
                    sanitized_dict[str_k] = "[REDACTED_SECRET]"
            else:
                sanitized_dict[str_k] = sanitize_sensitive_data(v)
        return sanitized_dict
    if isinstance(obj, (list, tuple)):
        return [sanitize_sensitive_data(item) for item in obj]
    if isinstance(obj, set):
        return {sanitize_sensitive_data(item) for item in obj}
    return obj


def compute_redaction_fingerprint(payload: str) -> str:
    """Compute SHA-256 seal fingerprint verifying compliance export integrity."""
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
