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
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.vector.base import FilterDict

if TYPE_CHECKING:
    from qdrant_client.models import Filter

_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def point_id_for(id_str: str) -> str:
    """Map a caller-facing id to a valid Qdrant UUID point id.

    Qdrant point ids must be valid UUIDs; non-UUID ids are remapped via
    uuid5 (deterministic, so the same caller id always maps to the same
    point id). Single source of truth shared by dense/sparse upserts and
    id filters — a HasIdCondition built from a caller-facing id must match
    the re-keyed point id the upsert actually stored, or the filter would
    silently match zero points.
    """
    import uuid

    try:
        uuid.UUID(id_str)
        return id_str
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_OID, id_str))


def _is_datetime_value(value: object) -> bool:
    """Detect ISO 8601 datetime string or datetime object."""
    if isinstance(value, datetime):
        return True
    return isinstance(value, str) and bool(_ISO8601_RE.match(value))


def _is_datetime_range(range_dict: Mapping[str, object]) -> bool:
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
        # Point-id values must go through the same deterministic re-key as
        # upsert (`point_id_for`): HasIdCondition matches the stored UUID point
        # id, while callers hold the original (pre-re-key) document id.
        if key == "id" and isinstance(value, list):
            conditions.append(HasIdCondition(has_id=[point_id_for(str(v)) for v in value]))
        elif key == "id" and isinstance(value, dict) and isinstance((in_value := value.get("$in")), list):
            # Local binding keeps the value a narrowed list for the comprehension
            # (a bare value["$in"] stays the full FilterDict value union).
            conditions.append(HasIdCondition(has_id=[point_id_for(str(v)) for v in in_value]))
        elif key == "id" and (isinstance(value, str) or type(value) is int):
            conditions.append(HasIdCondition(has_id=[point_id_for(str(value))]))
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
            conditions.append(FieldCondition(key=key, match=MatchAny(any=value)))
        else:
            conditions.append(
                FieldCondition(key=key, match=MatchValue(value=value))  # type: ignore[arg-type]
            )

    return Filter(
        must=conditions or None,
        must_not=must_not_conditions or None,
    )
