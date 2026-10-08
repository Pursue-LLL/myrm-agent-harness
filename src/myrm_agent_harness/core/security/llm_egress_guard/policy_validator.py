"""Domain and URL validation logic for LLM egress default-deny policies.

[INPUT]
- Target URLs, hostnames, domain patterns, and credential IDs.

[OUTPUT]
- Canonical host extraction and wildcard pattern matching results.

[POS]
- Harness core security validator enforcing strict fail-closed egress boundaries.
"""

from __future__ import annotations

import fnmatch
import urllib.parse


def extract_canonical_host(target: str) -> str:
    """Extract canonical lowercase hostname from URL or raw host string."""
    clean_target = target.strip()
    if "://" in clean_target:
        parsed = urllib.parse.urlparse(clean_target)
        host = parsed.hostname or parsed.netloc.split(":")[0]
    else:
        # Strip port and path if present
        host = clean_target.split("/")[0].split(":")[0]
    return host.lower().strip()


def matches_domain_pattern(host: str, pattern: str) -> bool:
    """Match host against exact domain or wildcard pattern (e.g. *.openai.azure.com)."""
    norm_host = host.lower().strip()
    norm_pattern = pattern.lower().strip()

    if norm_host == norm_pattern:
        return True

    if norm_pattern.startswith("*."):
        suffix = norm_pattern[2:]
        # Host must end with .suffix or be exactly suffix
        return norm_host == suffix or norm_host.endswith(f".{suffix}")

    return fnmatch.fnmatch(norm_host, norm_pattern)
