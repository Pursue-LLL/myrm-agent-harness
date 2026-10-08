"""Swap-on-Access L7 Egress Proxy inspecting outbound traffic and swapping credentials."""

from __future__ import annotations

import re
import time

from .placeholder_registry import PlaceholderRegistry
from .types import (
    BoundCredentialSpec,
    ProxyInspectionResult,
    SwapEvent,
)


class SwapOnAccessProxy:
    """L7 egress proxy interceptor enforcing secretless sandbox operation.

    Guarantees:
    1. Zero real credentials inside sandbox container.
    2. Outgoing requests to target host dynamically receive injected Authorization headers.
    3. Placeholders exfiltrated to non-target domains are strictly blocked with HTTP 403.
    """

    def __init__(self, registry: PlaceholderRegistry | None = None) -> None:
        self._registry = registry or PlaceholderRegistry()
        self._audit_events: list[SwapEvent] = []

    @property
    def registry(self) -> PlaceholderRegistry:
        """Access underlying PlaceholderRegistry."""
        return self._registry

    def _find_placeholder_in_headers(
        self, headers: dict[str, str]
    ) -> tuple[str | None, str | None]:
        """Scan header values for any registered or synthetic placeholder token.

        Returns (header_name, matched_placeholder) or (None, None).
        """
        for h_name, h_val in headers.items():
            for placeholder in self._registry.list_all_placeholders():
                if placeholder in h_val:
                    return h_name, placeholder
            matched = re.search(r"myrm_cred_[0-9a-fA-F]+", h_val)
            if matched:
                return h_name, matched.group(0)
        return None, None

    def inspect_and_swap(
        self,
        target_host: str,
        path: str = "/",
        method: str = "GET",
        headers: dict[str, str] | None = None,
    ) -> ProxyInspectionResult:
        """Inspect outbound request, guard against cross-domain leaks, and inject real credentials."""
        now = time.time()
        clean_host = self._registry._normalize_host(target_host)
        in_headers = dict(headers or {})

        header_key, placeholder_found = self._find_placeholder_in_headers(in_headers)

        # Case 1: Header contains a placeholder token
        if placeholder_found:
            bound_spec = self._registry.get_by_placeholder(placeholder_found)
            if bound_spec is None:
                event = SwapEvent(
                    timestamp=now,
                    target_host=clean_host,
                    path=path,
                    method=method,
                    placeholder_used=placeholder_found,
                    is_swapped=False,
                    is_blocked=True,
                    block_reason="Unrecognized or revoked placeholder",
                )
                self._audit_events.append(event)
                return ProxyInspectionResult(
                    is_allowed=False,
                    status_code=403,
                    reason="Forbidden: placeholder token is invalid or revoked.",
                    event=event,
                )

            # Check cross-domain exfiltration
            if bound_spec.target_host != clean_host:
                event = SwapEvent(
                    timestamp=now,
                    target_host=clean_host,
                    path=path,
                    method=method,
                    placeholder_used=placeholder_found,
                    is_swapped=False,
                    is_blocked=True,
                    block_reason=(
                        f"Cross-domain exfiltration blocked: placeholder bound to "
                        f"'{bound_spec.target_host}' was directed to '{clean_host}'"
                    ),
                )
                self._audit_events.append(event)
                return ProxyInspectionResult(
                    is_allowed=False,
                    status_code=403,
                    reason=(
                        f"Forbidden: cross-domain exfiltration attempt blocked. Placeholder bound to "
                        f"'{bound_spec.target_host}' was directed to untrusted host '{clean_host}'."
                    ),
                    event=event,
                )

            # Legitimate destination: swap placeholder for real secret
            out_headers: dict[str, str] = {}
            if header_key:
                original_val = in_headers[header_key]
                swapped_val = original_val.replace(placeholder_found, bound_spec.real_secret)
                out_headers[header_key] = swapped_val

            event = SwapEvent(
                timestamp=now,
                target_host=clean_host,
                path=path,
                method=method,
                placeholder_used=placeholder_found,
                is_swapped=True,
                is_blocked=False,
            )
            self._audit_events.append(event)
            return ProxyInspectionResult(
                is_allowed=True,
                status_code=200,
                headers_to_inject=out_headers,
                reason="Placeholder successfully swapped with real credential.",
                event=event,
            )

        # Case 2: No placeholder in header, but target_host is registered for automatic swap-on-access
        bound_spec_by_host: BoundCredentialSpec | None = self._registry.get_by_host(clean_host)
        if bound_spec_by_host:
            auth_header_val = bound_spec_by_host.auth_header_template.replace(
                "{secret}", bound_spec_by_host.real_secret
            )
            injected = {bound_spec_by_host.auth_header_name: auth_header_val}
            event = SwapEvent(
                timestamp=now,
                target_host=clean_host,
                path=path,
                method=method,
                placeholder_used=None,
                is_swapped=True,
                is_blocked=False,
            )
            self._audit_events.append(event)
            return ProxyInspectionResult(
                is_allowed=True,
                status_code=200,
                headers_to_inject=injected,
                reason="Automatic Swap-on-Access injected bound credentials.",
                event=event,
            )

        # Case 3: Standard unauthenticated outbound traffic
        event = SwapEvent(
            timestamp=now,
            target_host=clean_host,
            path=path,
            method=method,
            placeholder_used=None,
            is_swapped=False,
            is_blocked=False,
        )
        self._audit_events.append(event)
        return ProxyInspectionResult(
            is_allowed=True,
            status_code=200,
            headers_to_inject={},
            reason="Unauthenticated request passed transparently.",
            event=event,
        )

    def get_audit_events(self, limit: int = 100) -> list[SwapEvent]:
        """Retrieve recent swap and exfiltration audit events."""
        return self._audit_events[-limit:]
