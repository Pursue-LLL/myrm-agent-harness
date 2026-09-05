from datetime import datetime

from myrm_agent_harness.toolkits.vector.qdrant.filters import build_qdrant_filter


def test_build_qdrant_filter_empty():
    assert build_qdrant_filter(None) is None
    assert build_qdrant_filter({}) is None


def test_build_qdrant_filter_match_value():
    from qdrant_client.models import MatchValue

    f = build_qdrant_filter({"key": "value"})
    assert len(f.must) == 1
    assert f.must[0].key == "key"
    assert isinstance(f.must[0].match, MatchValue)
    assert f.must[0].match.value == "value"


def test_build_qdrant_filter_match_any():
    from qdrant_client.models import MatchAny

    f = build_qdrant_filter({"key": ["val1", "val2"]})
    assert len(f.must) == 1
    assert f.must[0].key == "key"
    assert isinstance(f.must[0].match, MatchAny)
    assert f.must[0].match.any == ["val1", "val2"]


def test_build_qdrant_filter_match_except():
    from qdrant_client.models import MatchExcept

    f = build_qdrant_filter({"key": {"not": "value"}})
    assert len(f.must) == 1
    assert f.must[0].key == "key"
    assert isinstance(f.must[0].match, MatchExcept)
    assert getattr(f.must[0].match, "except_", None) == ["value"] or getattr(f.must[0].match, "except", None) == [
        "value"
    ]


def test_build_qdrant_filter_not_bool_uses_must_not():
    from qdrant_client.models import MatchValue

    f = build_qdrant_filter({"archived": {"not": True}})
    assert f.must is None or len(f.must) == 0
    assert len(f.must_not) == 1
    assert f.must_not[0].key == "archived"
    assert isinstance(f.must_not[0].match, MatchValue)
    assert f.must_not[0].match.value is True


def test_build_qdrant_filter_range():
    from qdrant_client.models import Range

    f = build_qdrant_filter({"key": {"gte": 0, "lte": 100}})
    assert len(f.must) == 1
    assert f.must[0].key == "key"
    assert isinstance(f.must[0].range, Range)
    assert f.must[0].range.gte == 0
    assert f.must[0].range.lte == 100


def test_build_qdrant_filter_datetime_range():
    from qdrant_client.models import DatetimeRange

    f = build_qdrant_filter({"key": {"gte": "2026-01-01T00:00:00", "lte": datetime.now()}})
    assert len(f.must) == 1
    assert f.must[0].key == "key"
    assert isinstance(f.must[0].range, DatetimeRange)
    assert f.must[0].range.gte.strftime("%Y-%m-%dT%H:%M:%S") == "2026-01-01T00:00:00"
    assert f.must[0].range.lte is not None


def test_build_qdrant_filter_has_id():
    from qdrant_client.models import HasIdCondition

    f = build_qdrant_filter({"id": {"$in": ["m1", "m2"]}})
    assert len(f.must) == 1
    assert isinstance(f.must[0], HasIdCondition)
    assert f.must[0].has_id == ["m1", "m2"]


def test_build_qdrant_filter_id_list_uses_has_id():
    from qdrant_client.models import HasIdCondition

    f = build_qdrant_filter({"id": ["m1", "m2"]})
    assert len(f.must) == 1
    assert isinstance(f.must[0], HasIdCondition)
    assert f.must[0].has_id == ["m1", "m2"]


def test_build_qdrant_filter_id_list_mixed_with_field_filter():
    from qdrant_client.models import HasIdCondition, MatchValue

    f = build_qdrant_filter({"archived": False, "id": ["m1"]})
    assert len(f.must) == 2
    assert f.must[0].key == "archived"
    assert isinstance(f.must[0].match, MatchValue)
    assert isinstance(f.must[1], HasIdCondition)
    assert f.must[1].has_id == ["m1"]


def test_build_qdrant_filter_mixed_with_has_id():
    from qdrant_client.models import HasIdCondition, MatchValue

    f = build_qdrant_filter({"archived": False, "id": {"$in": ["m1"]}})
    assert len(f.must) == 2
    assert f.must[0].key == "archived"
    assert isinstance(f.must[0].match, MatchValue)
    assert isinstance(f.must[1], HasIdCondition)
    assert f.must[1].has_id == ["m1"]


def test_build_qdrant_filter_id_plain_value_uses_has_id():
    from qdrant_client.models import HasIdCondition

    f = build_qdrant_filter({"id": "plain-value"})
    assert len(f.must) == 1
    assert isinstance(f.must[0], HasIdCondition)
    assert f.must[0].has_id == ["plain-value"]


def test_build_qdrant_filter_id_int_value_uses_has_id():
    from qdrant_client.models import HasIdCondition

    f = build_qdrant_filter({"id": 42})
    assert len(f.must) == 1
    assert isinstance(f.must[0], HasIdCondition)
    assert f.must[0].has_id == [42]


def test_build_qdrant_filter_id_plain_mixed_with_field_filter():
    from qdrant_client.models import HasIdCondition, MatchValue

    f = build_qdrant_filter({"archived": False, "id": "m1"})
    assert len(f.must) == 2
    assert f.must[0].key == "archived"
    assert isinstance(f.must[0].match, MatchValue)
    assert isinstance(f.must[1], HasIdCondition)
    assert f.must[1].has_id == ["m1"]


def test_build_qdrant_filter_id_bool_not_has_id():
    # bool is a valid FilterDict scalar but never a point id; it must fall
    # through to the generic match instead of raising a HasIdCondition error.
    from qdrant_client.models import MatchValue

    f = build_qdrant_filter({"id": True})
    assert len(f.must) == 1
    assert f.must[0].key == "id"
    assert isinstance(f.must[0].match, MatchValue)


def test_build_qdrant_filter_id_empty_in_narrows_to_zero():
    # An empty ``$in`` or list-value ID query builds an empty HasIdCondition.
    # Real Qdrant treats it as an empty point-id set: 0 matches, no crash.
    from qdrant_client.models import HasIdCondition

    f = build_qdrant_filter({"id": {"$in": []}})
    assert isinstance(f.must[0], HasIdCondition)
    assert f.must[0].has_id == []
    f = build_qdrant_filter({"id": []})
    assert isinstance(f.must[0], HasIdCondition)
    assert f.must[0].has_id == []


def test_build_qdrant_filter_id_float_none_fail_fast():
    # float/None are outside the FilterDict value contract for point ids; they
    # fall through to MatchValue and raise at construction time (same behavior
    # as for any other payload field — a pre-existing generic fail-fast path).
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        build_qdrant_filter({"id": 1.5})
    with pytest.raises(ValidationError):
        build_qdrant_filter({"id": None})
