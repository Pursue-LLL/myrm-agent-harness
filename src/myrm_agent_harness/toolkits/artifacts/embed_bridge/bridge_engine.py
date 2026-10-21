"""[INPUT]
- models: HostContextSnapshot, HostBridgeMessage, EmbedSecurityPolicy, BridgeInjectedContext

[OUTPUT]
- HostContextBridgeEngine: Core engine governing cross-origin verification, context compiling, and bidirectional IPC message flow

[POS]
Harness framework layer engine for Embeddable Agent Widget & Host Context Bridge (Item 41 P1).
Strictly under 160 lines. Zero `Any`.
"""

from __future__ import annotations

import threading
from urllib.parse import urlparse

from .models import (
    BridgeInjectedContext,
    EmbedSecurityPolicy,
    HostContextSnapshot,
)


class HostContextBridgeEngine:
    """Thread-safe engine governing host-to-agent context injection and embed security verification."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._injected_contexts: dict[str, list[BridgeInjectedContext]] = {}

    @staticmethod
    def validate_origin(origin: str, policy: EmbedSecurityPolicy) -> bool:
        """Verifies if the given request origin is permitted under security policy."""
        if not origin:
            return False

        if "*" in policy.allowed_origins:
            return True

        normalized_origin = origin.strip().rstrip("/").lower()
        for allowed in policy.allowed_origins:
            cleaned = allowed.strip().rstrip("/").lower()
            if cleaned == normalized_origin:
                return True
            # Wildcard subdomain support e.g. *.example.com
            if cleaned.startswith("*."):
                domain_part = cleaned[2:]
                parsed = urlparse(normalized_origin)
                hostname = parsed.hostname or ""
                if hostname == domain_part or hostname.endswith("." + domain_part):
                    return True

        return False

    def compile_context_prompt(
        self,
        snapshot: HostContextSnapshot,
        policy: EmbedSecurityPolicy | None = None,
    ) -> str:
        """Transforms host webpage metadata and form fields into structured @host_context prompt."""
        pol = policy or EmbedSecurityPolicy()
        lines: list[str] = [
            "### [@host_context: External Host Webpage Snapshot]",
            f"- Origin: {snapshot.origin}",
            f"- Current URL: {snapshot.current_url}",
        ]

        if snapshot.page_title:
            lines.append(f"- Page Title: {snapshot.page_title}")

        if pol.allow_selection_capture and snapshot.selected_text:
            lines.append(f"- User Selected Text: \"{snapshot.selected_text.strip()}\"")

        if pol.allow_form_capture and snapshot.form_fields:
            lines.append("- Active Form Fields:")
            for field_name, field_val in snapshot.form_fields.items():
                lines.append(f"  * {field_name}: {field_val}")

        if snapshot.user_metadata:
            lines.append("- Host Metadata:")
            for meta_k, meta_v in snapshot.user_metadata.items():
                lines.append(f"  * {meta_k}: {meta_v}")

        lines.append(
            "\nINSTRUCTION: The above context reflects the active webpage where the user embedded this agent. "
            "Prioritize this context when answering queries about current data, orders, or page content."
        )

        return "\n".join(lines)

    def inject_context(
        self,
        session_id: str,
        snapshot: HostContextSnapshot,
        policy: EmbedSecurityPolicy,
    ) -> BridgeInjectedContext:
        """Verifies origin, compiles context text, and records injection into session history."""
        if not self.validate_origin(snapshot.origin, policy):
            raise PermissionError(
                f"Origin '{snapshot.origin}' is not permitted by embed security policy"
            )

        context_text = self.compile_context_prompt(snapshot, policy)
        injected = BridgeInjectedContext(
            session_id=session_id,
            context_text=context_text,
            snapshot=snapshot,
        )

        with self._lock:
            contexts = self._injected_contexts.setdefault(session_id, [])
            contexts.append(injected)

        return injected

    def get_latest_context(self, session_id: str) -> BridgeInjectedContext | None:
        """Retrieves the most recent injected host context for the session."""
        with self._lock:
            contexts = self._injected_contexts.get(session_id, [])
            return contexts[-1] if contexts else None
