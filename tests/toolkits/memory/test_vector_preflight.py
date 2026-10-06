# [POS] tests/toolkits/memory/test_vector_preflight.py
# [INPUT] pytest, myrm_agent_harness.toolkits.memory.vector_preflight
# [OUTPUT] test_loopback_sanitizer_host_normalization, test_loopback_sanitizer_full_endpoint_uris, test_dimension_integrity_probe_match_and_mismatch, test_dimension_integrity_probe_dynamic_sampling

from myrm_agent_harness.toolkits.memory.vector_preflight import (
    DimensionIntegrityProbe,
    DimensionIntegrityReport,
    IPv4LoopbackSanitizer,
    PreflightHealthStatus,
    SanitizedEndpointResult,
)


def test_loopback_sanitizer_host_normalization() -> None:
    """Verify IPv4LoopbackSanitizer normalizes localhost and IPv6 loopback to 127.0.0.1."""
    # 1. 'localhost' -> '127.0.0.1'
    host_res, modified, reason = IPv4LoopbackSanitizer.sanitize_host("localhost")
    assert host_res == "127.0.0.1"
    assert modified is True
    assert "IPv6 ::1" in reason

    # 2. '::1' -> '127.0.0.1'
    host_res_v6, modified_v6, _ = IPv4LoopbackSanitizer.sanitize_host("::1")
    assert host_res_v6 == "127.0.0.1"
    assert modified_v6 is True

    # 3. '[::1]' -> '127.0.0.1'
    host_res_bracket, modified_bracket, _ = IPv4LoopbackSanitizer.sanitize_host("[::1]")
    assert host_res_bracket == "127.0.0.1"
    assert modified_bracket is True

    # 4. Standard external host or valid IP untouched
    host_ext, mod_ext, _ = IPv4LoopbackSanitizer.sanitize_host("qdrant.production.internal")
    assert host_ext == "qdrant.production.internal"
    assert mod_ext is False

    host_ip, mod_ip, _ = IPv4LoopbackSanitizer.sanitize_host("192.168.1.100")
    assert host_ip == "192.168.1.100"
    assert mod_ip is False


def test_loopback_sanitizer_full_endpoint_uris() -> None:
    """Verify complete URIs with schemes and ports are cleanly sanitized without losing path or query."""
    # HTTP URL
    res_http: SanitizedEndpointResult = IPv4LoopbackSanitizer.sanitize_endpoint("http://localhost:6333/dashboard")
    assert res_http.was_modified is True
    assert res_http.sanitized_endpoint == "http://127.0.0.1:6333/dashboard"

    # gRPC URL
    res_grpc: SanitizedEndpointResult = IPv4LoopbackSanitizer.sanitize_endpoint("grpc://localhost:6334")
    assert res_grpc.was_modified is True
    assert res_grpc.sanitized_endpoint == "grpc://127.0.0.1:6334"

    # Host:port without scheme
    res_plain: SanitizedEndpointResult = IPv4LoopbackSanitizer.sanitize_endpoint("localhost:6333")
    assert res_plain.was_modified is True
    assert res_plain.sanitized_endpoint == "127.0.0.1:6333"

    # Already sanitized
    res_already: SanitizedEndpointResult = IPv4LoopbackSanitizer.sanitize_endpoint("http://127.0.0.1:6333")
    assert res_already.was_modified is False
    assert res_already.sanitized_endpoint == "http://127.0.0.1:6333"


def test_dimension_integrity_probe_match_and_mismatch() -> None:
    """Verify rigid dimension integrity checking prevents silent crash from mismatching embedding sizes."""
    # 1. Perfect match (1536 dims)
    rep_match: DimensionIntegrityReport = DimensionIntegrityProbe.verify_dimension_integrity(
        actual_dims=1536,
        expected_dims=1536,
        embedder_name="text-embedding-3-small",
        collection_name="user_memories",
    )
    assert rep_match.is_valid is True
    assert rep_match.status == PreflightHealthStatus.HEALTHY
    assert "perfectly matches" in rep_match.diagnosis
    assert rep_match.suggested_action == ""

    # 2. Mismatch (Qwen3 2560 vs Collection 1536)
    rep_mismatch: DimensionIntegrityReport = DimensionIntegrityProbe.verify_dimension_integrity(
        actual_dims=2560,
        expected_dims=1536,
        embedder_name="Qwen3-Embedding-4B",
        collection_name="user_memories",
    )
    assert rep_mismatch.is_valid is False
    assert rep_mismatch.status == PreflightHealthStatus.MISMATCH_BLOCKED
    assert "mismatch detected" in rep_mismatch.diagnosis
    assert "2560" in rep_mismatch.diagnosis
    assert "1536" in rep_mismatch.diagnosis
    assert "Recreate collection" in rep_mismatch.suggested_action

    # 3. Invalid inputs
    rep_invalid = DimensionIntegrityProbe.verify_dimension_integrity(actual_dims=0, expected_dims=1536)
    assert rep_invalid.is_valid is False
    assert rep_invalid.status == PreflightHealthStatus.INVALID_CONFIGURATION


def test_dimension_integrity_probe_dynamic_sampling() -> None:
    """Verify dynamic sampling executes probe callable to derive actual dimensions."""
    def mock_bge(_text: str) -> list[float]:
        return [0.1] * 1024

    report = DimensionIntegrityProbe.sample_and_verify(
        embed_fn=mock_bge,
        expected_dims=1024,
        embedder_name="bge-large-zh-v1.5",
        collection_name="wiki_embeddings",
    )
    assert report.is_valid is True
    assert report.actual_dims == 1024
    assert report.status == PreflightHealthStatus.HEALTHY

    # Failing callable
    def failing_embedder(_text: str) -> list[float]:
        msg = "Authentication token expired"
        raise ConnectionError(msg)

    report_fail = DimensionIntegrityProbe.sample_and_verify(
        embed_fn=failing_embedder,
        expected_dims=1024,
        embedder_name="failing_cloud_embedder",
    )
    assert report_fail.is_valid is False
    assert report_fail.status == PreflightHealthStatus.INVALID_CONFIGURATION
    assert "Authentication token expired" in report_fail.diagnosis
