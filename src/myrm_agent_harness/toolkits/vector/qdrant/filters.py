"""Qdrant Filter Builder.

[INPUT]
qdrant_client.models (POS: Qdrant SDK filter models, optional dependency)

[OUTPUT]
build_qdrant_filter: Convert dict filter syntax to Qdrant Filter object

[POS]
Qdrant filter builder. Converts generic dict filter syntax to Qdrant SDK Filter objects.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.vector.base import FilterDict

if TYPE_CHECKING:
    from qdrant_client.models import Filter

_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def _is_datetime_value(value: object) -> bool:
    """Detect ISO 8601 datetime string or datetime object."""
    if isinstance(value, datetime):
        return True
    return isinstance(value, str) and bool(_ISO8601_RE.match(value))


def _is_datetime_range(range_dict: dict[str, object]) -> bool:
    """Check if any range bound is a datetime value."""
    return any(_is_datetime_value(range_dict.get(k, 0)) for k in ("gt", "gte", "lt", "lte"))


def build_qdrant_filter(filters: FilterDict | None) -> Filter | None:
    """Build Qdrant filter from dict.

    Supported syntax:
    - Simple match: ``{"key": "value"}``
    - IN query: ``{"key": ["val1", "val2"]}``
    - Numeric range: ``{"key": {"gte": 0, "lte": 100}}``
    - Datetime range: ``{"key": {"gte": "2026-01-01T00:00:00", "lte": "2026-12-31T..."}}``
    - NOT query: ``{"key": {"not": "value"}}``
    - Point ID queries (``id`` targets the Qdrant point id, not a payload field):
      ``{"id": "point-id"}`` or ``{"id": ["point-id-1", "point-id-2"]}`` or
      ``{"id": {"$in": ["point-id-1", "point-id-2"]}}``
    """
    if not filters:
        return None

    from qdrant_client.models import (
        Condition,
        DatetimeRange,
        FieldCondition,
        Filter,
        HasIdCondition,
        MatchAny,
        MatchExcept,
        MatchValue,
        Range,
    )

    conditions: list[Condition] = []
    must_not_conditions: list[Condition] = []

    for key, value in filters.items():
        if key == "id" and isinstance(value, list):
            conditions.append(HasIdCondition(has_id=value))
        elif key == "id" and isinstance(value, dict) and value.get("$in") is not None:
            conditions.append(HasIdCondition(has_id=value["$in"]))
        elif key == "id" and (isinstance(value, str) or type(value) is int):
            conditions.append(HasIdCondition(has_id=[value]))  # type: ignore[arg-type]
        elif isinstance(value, dict):
            if "not" in value:
                not_val = value["not"]
                if isinstance(not_val, bool):
                    must_not_conditions.append(
                        FieldCondition(
                            key=key,
                            match=MatchValue(value=not_val),
                        )
                    )
                else:
                    conditions.append(
                        FieldCondition(
                            key=key,
                            match=MatchExcept(**{"except": [not_val]}),  # type: ignore[arg-type]
                        )
                    )
            elif any(k in value for k in ("gt", "gte", "lt", "lte")):
                if _is_datetime_range(value):
                    conditions.append(
                        FieldCondition(
                            key=key,
                            range=DatetimeRange(
                                gt=value.get("gt"),  # type: ignore[arg-type]
                                gte=value.get("gte"),  # type: ignore[arg-type]
                                lt=value.get("lt"),  # type: ignore[arg-type]
                                lte=value.get("lte"),  # type: ignore[arg-type]
                            ),
                        )
                    )
                else:
                    conditions.append(
                        FieldCondition(
                            key=key,
                            range=Range(
                                gt=value.get("gt"),  # type: ignore[arg-type]
                                gte=value.get("gte"),  # type: ignore[arg-type]
                                lt=value.get("lt"),  # type: ignore[arg-type]
                                lte=value.get("lte"),  # type: ignore[arg-type]
                            ),
                        )
                    )
        elif isinstance(value, list):
            conditions.append(
                FieldCondition(key=key, match=MatchAny(any=value))  # type: ignore[arg-type]
            )
        else:
            conditions.append(
                FieldCondition(key=key, match=MatchValue(value=value))  # type: ignore[arg-type]
            )

    return Filter(
        must=conditions or None,
        must_not=must_not_conditions or None,
    )
