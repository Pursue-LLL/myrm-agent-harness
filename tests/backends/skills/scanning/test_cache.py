"""Unit tests for ScanResultCache."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills.scanning.cache import (
    ScanResultCache,
    get_scan_cache,
)
from myrm_agent_harness.backends.skills.scanning.scanner import (
    ScanFinding,
    ScanResult,
    ScanSeverity,
)


@pytest.fixture
def temp_cache(tmp_path: Path) -> ScanResultCache:
    """Create a temporary cache instance."""
    return ScanResultCache(cache_dir=tmp_path, ttl_days=1)


@pytest.fixture
def sample_result() -> ScanResult:
    """Create a sample scan result."""
    return ScanResult(
        skill_name="test-skill",
        findings=[
            ScanFinding(
                threat_type="Network",
                severity=ScanSeverity.HIGH,
                description="Test finding",
                line_number=10,
            )
        ],
    )


def test_cache_miss(temp_cache: ScanResultCache):
    """Test cache miss returns None."""
    result = temp_cache.get("nonexistent content")
    assert result is None


def test_cache_hit(temp_cache: ScanResultCache, sample_result: ScanResult):
    """Test cache hit returns correct ScanResult."""
    content = "test skill content"
    temp_cache.set(content, sample_result)

    cached_result = temp_cache.get(content)
    assert cached_result is not None
    assert cached_result.skill_name == sample_result.skill_name
    assert len(cached_result.findings) == len(sample_result.findings)
    assert cached_result.findings[0].threat_type == "Network"


def test_cache_expired(tmp_path: Path, sample_result: ScanResult):
    """Test TTL expiration removes cached entry."""
    cache = ScanResultCache(cache_dir=tmp_path, ttl_days=0)  # Immediate expiration
    content = "test content"

    # Set cache
    cache.set(content, sample_result)

    # Manually modify cached_at to past
    content_hash = cache._compute_hash(content)
    cache_file = cache._cache_path(content_hash)
    with cache_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data["cached_at"] = (datetime.now() - timedelta(days=2)).isoformat()
    with cache_file.open("w", encoding="utf-8") as f:
        json.dump(data, f)

    # Get should return None and delete file
    result = cache.get(content)
    assert result is None
    assert not cache_file.exists()


def test_cache_set_get(temp_cache: ScanResultCache, sample_result: ScanResult):
    """Test set followed by immediate get."""
    content = "test content"
    temp_cache.set(content, sample_result)

    result = temp_cache.get(content)
    assert result is not None
    assert result.skill_name == "test-skill"


def test_cache_hash_consistency(temp_cache: ScanResultCache):
    """Test same content generates same hash."""
    content = "identical content"
    hash1 = temp_cache._compute_hash(content)
    hash2 = temp_cache._compute_hash(content)
    assert hash1 == hash2


def test_cache_different_content(temp_cache: ScanResultCache, sample_result: ScanResult):
    """Test different content does not conflict."""
    content1 = "first content"
    content2 = "second content"

    result1 = ScanResult(skill_name="skill1", findings=[])
    result2 = ScanResult(skill_name="skill2", findings=[])

    temp_cache.set(content1, result1)
    temp_cache.set(content2, result2)

    cached1 = temp_cache.get(content1)
    cached2 = temp_cache.get(content2)

    assert cached1 is not None
    assert cached2 is not None
    assert cached1.skill_name == "skill1"
    assert cached2.skill_name == "skill2"


def test_cache_corrupted_json(tmp_path: Path, sample_result: ScanResult):
    """Test corrupted JSON file gracefully falls back."""
    cache = ScanResultCache(cache_dir=tmp_path)
    content = "test content"

    # Set cache
    cache.set(content, sample_result)

    # Corrupt JSON file
    content_hash = cache._compute_hash(content)
    cache_file = cache._cache_path(content_hash)
    with cache_file.open("w", encoding="utf-8") as f:
        f.write("invalid json {{{")

    # Get should return None and remove corrupted file
    result = cache.get(content)
    assert result is None
    assert not cache_file.exists()


def test_cache_dir_creation(tmp_path: Path):
    """Test cache directory is auto-created."""
    cache_dir = tmp_path / "new_cache_dir"
    assert not cache_dir.exists()

    ScanResultCache(cache_dir=cache_dir)
    assert cache_dir.exists()


def test_clear_expired(tmp_path: Path, sample_result: ScanResult):
    """Test clear_expired removes old entries."""
    cache = ScanResultCache(cache_dir=tmp_path, ttl_days=1)

    # Create expired entry
    content1 = "expired content"
    cache.set(content1, sample_result)
    content_hash1 = cache._compute_hash(content1)
    cache_file1 = cache._cache_path(content_hash1)
    with cache_file1.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data["cached_at"] = (datetime.now() - timedelta(days=2)).isoformat()
    with cache_file1.open("w", encoding="utf-8") as f:
        json.dump(data, f)

    # Create fresh entry
    content2 = "fresh content"
    cache.set(content2, sample_result)

    # Clear expired
    removed = cache.clear_expired()
    assert removed == 1
    assert not cache_file1.exists()
    assert cache.get(content2) is not None


def test_custom_ttl(tmp_path: Path, sample_result: ScanResult):
    """Test custom TTL is respected."""
    cache = ScanResultCache(cache_dir=tmp_path, ttl_days=10)
    assert cache.ttl_days == 10


def test_global_cache_singleton():
    """Test get_scan_cache returns global singleton."""
    cache1 = get_scan_cache()
    cache2 = get_scan_cache()
    assert cache1 is cache2
