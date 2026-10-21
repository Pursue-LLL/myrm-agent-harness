"""Dynamic Dev Port Sniffer.

[INPUT]
- Raw execution output, stdout/stderr chunk strings

[OUTPUT]
- DiscoveredPort dataclass
- sniff_ports_from_text: Parses dev server listening ports from execution logs

[POS]
Execution-log utility that surfaces dev-server listening ports so a UI can offer a preview of the sandbox service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveredPort:
    """Represents a network port discovered from dev execution output."""

    port: int
    process_name: str
    protocol: str
    url: str
    raw_match: str


# Regex rules for popular modern web and backend development servers
_SNIFFER_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # Next.js / Vite / Nuxt dev servers: "Local: http://localhost:3000"
    (
        re.compile(
            r"(?:Local|Network):\s+(?P<proto>https?)://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?P<port>\d{2,5})",
            re.IGNORECASE,
        ),
        "vite/next-dev",
        "http",
    ),
    # Uvicorn / FastAPI / Starlette: "Uvicorn running on http://127.0.0.1:8000"
    (
        re.compile(
            r"Uvicorn\s+running\s+on\s+(?P<proto>https?)://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?P<port>\d{2,5})",
            re.IGNORECASE,
        ),
        "uvicorn",
        "http",
    ),
    # Flask / Werkzeug: "Running on http://127.0.0.1:5000"
    (
        re.compile(
            r"Running\s+on\s+(?P<proto>https?)://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?P<port>\d{2,5})",
            re.IGNORECASE,
        ),
        "flask",
        "http",
    ),
    # Python http.server: "Serving HTTP on 0.0.0.0 port 8000"
    (
        re.compile(
            r"Serving\s+HTTP\s+on\s+(?:0\.0\.0\.0|::|localhost|127\.0\.0\.1)\s+port\s+(?P<port>\d{2,5})",
            re.IGNORECASE,
        ),
        "python-http",
        "http",
    ),
    # Node / Express / Fastify / Koa: "Listening on http://localhost:4000" or "Server listening on port 3000"
    (
        re.compile(
            r"(?:server|app|service)?\s*(?:is\s+)?listening\s*(?:at|on)?\s*(?:port)?\s*:?\s*(?:(?P<proto>https?)://)?(?:localhost|127\.0\.0\.1|0\.0\.0\.0)?:?(?P<port>\d{2,5})",
            re.IGNORECASE,
        ),
        "node-server",
        "http",
    ),
    # Generic localhost URL pattern: "http://localhost:8080"
    (
        re.compile(
            r"(?P<proto>https?)://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?P<port>\d{2,5})",
            re.IGNORECASE,
        ),
        "dev-service",
        "http",
    ),
]


def sniff_ports_from_text(text: str) -> list[DiscoveredPort]:
    """Inspects stdout or stderr log chunk to discover active listening ports.

    Args:
        text: Raw terminal output string.

    Returns:
        Deduplicated list of discovered port entries ordered by first appearance.
    """
    if not text or not text.strip():
        return []

    discovered: dict[int, DiscoveredPort] = {}

    for pattern, default_process, default_proto in _SNIFFER_PATTERNS:
        for match in pattern.finditer(text):
            try:
                port_val = int(match.group("port"))
            except (ValueError, IndexError):
                continue

            # Validate valid TCP port range (exclude system port 0 and out-of-bounds > 65535)
            if port_val <= 0 or port_val > 65535:
                continue

            if port_val in discovered:
                continue

            proto = (match.groupdict().get("proto") or default_proto).lower()
            url = f"{proto}://localhost:{port_val}"
            matched_str = match.group(0)

            discovered[port_val] = DiscoveredPort(
                port=port_val,
                process_name=default_process,
                protocol=proto,
                url=url,
                raw_match=matched_str,
            )

    return list(discovered.values())
