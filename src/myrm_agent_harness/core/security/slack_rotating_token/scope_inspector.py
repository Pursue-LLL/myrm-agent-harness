"""Scope Inspector for Slack Tokens and OAuth Metadata.

[INPUT]
- SlackTokenType, token metadata mapping without Any types.

[OUTPUT]
- SlackScopeInspection DTO with resolved scope list and provenance source field.

[POS]
- Harness core security engine for OpenConnector #14c3a6c scope regression and routing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .types import (
    SlackScopeInspection,
    SlackTokenType,
)


class SlackScopeInspector:
    """Inspects and parses OAuth permissions associated with Slack tokens."""

    @staticmethod
    def _parse_scopes(raw_val: object) -> list[str]:
        """Parse raw scope value (string or list) into a deduplicated sorted list of strings."""
        if isinstance(raw_val, str):
            # Slack scopes can be comma-separated or space-separated
            raw_tokens = raw_val.replace(",", " ").split()
            return sorted({s.strip() for s in raw_tokens if s.strip()})
        if isinstance(raw_val, Sequence) and not isinstance(raw_val, (str, bytes)):
            scopes: set[str] = set()
            for item in raw_val:
                if isinstance(item, str) and item.strip():
                    scopes.add(item.strip())
            return sorted(scopes)
        return []

    def inspect_scopes(
        self,
        token_type: SlackTokenType,
        metadata: Mapping[str, object],
    ) -> SlackScopeInspection:
        """Inspect and extract authorized OAuth scopes for the given token type and metadata."""
        resolved: list[str] = []
        source_field = "none"

        if token_type == SlackTokenType.USER:
            # User tokens check metadata.authed_user.scope first
            authed_user_obj = metadata.get("authed_user")
            if isinstance(authed_user_obj, Mapping) and "scope" in authed_user_obj:
                parsed = self._parse_scopes(authed_user_obj.get("scope"))
                if parsed:
                    resolved = parsed
                    source_field = "authed_user.scope"

            # Fallback to top-level scope if authed_user not present or empty
            if not resolved and "scope" in metadata:
                parsed = self._parse_scopes(metadata.get("scope"))
                if parsed:
                    resolved = parsed
                    source_field = "scope"

        else:
            # Bot or default tokens check top-level scope first
            if "scope" in metadata:
                parsed = self._parse_scopes(metadata.get("scope"))
                if parsed:
                    resolved = parsed
                    source_field = "scope"

            # Fallback to authed_user.scope if top-level scope empty
            if not resolved:
                authed_user_obj = metadata.get("authed_user")
                if isinstance(authed_user_obj, Mapping) and "scope" in authed_user_obj:
                    parsed = self._parse_scopes(authed_user_obj.get("scope"))
                    if parsed:
                        resolved = parsed
                        source_field = "authed_user.scope"

        return SlackScopeInspection(
            token_type=token_type,
            resolved_scopes=resolved,
            source_field=source_field,
        )
