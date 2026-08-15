"""Small string/number coercion helpers shared by trace aggregation modules.

Kept in their own module so the aggregation modules (trace_builder and its
``_pairing``/``_llm``/``_tasks_steps`` helpers) can share them without
circular imports.
"""

from __future__ import annotations


def _str_or_none(value: object) -> str | None:
    """Safely extract a string or return None."""
    return str(value) if isinstance(value, str) else None


def _int_or_zero(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
