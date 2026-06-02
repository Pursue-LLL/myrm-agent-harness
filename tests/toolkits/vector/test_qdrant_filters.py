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
    assert getattr(f.must[0].match, "except_", None) == ["value"] or getattr(f.must[0].match, "except", None) == ["value"]

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
