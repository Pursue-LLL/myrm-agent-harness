"""Stable application identity helpers for desktop trust keys.

Trust keys prefer platform-stable app_id (bundle ID, process exe) over display names.
"""

from __future__ import annotations


def resolve_trust_key(*, app_name: str, app_id: str = "") -> str:
    """Return the canonical trust key for an application."""
    cleaned_id = app_id.strip()
    if cleaned_id:
        return cleaned_id
    cleaned_name = app_name.strip().lower()
    return cleaned_name


def trust_key_matches(
    stored_key: str,
    *,
    app_name: str,
    app_id: str = "",
) -> bool:
    """Return True when *stored_key* matches the resolved app identity."""
    candidate = resolve_trust_key(app_name=app_name, app_id=app_id)
    normalized_stored = stored_key.strip()
    if not normalized_stored:
        return False
    if normalized_stored == candidate:
        return True
    return normalized_stored == app_name.strip().lower()
