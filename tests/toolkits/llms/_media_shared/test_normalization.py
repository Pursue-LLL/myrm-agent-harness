"""Tests for _media_shared normalization engine."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms._media_shared.normalization import (
    derive_ratio_from_size,
    normalize_params,
    resolve_closest_duration,
    resolve_closest_ratio,
    resolve_closest_size,
)
from myrm_agent_harness.toolkits.llms._media_shared.types import (
    ModeCapabilities,
    SizeSpec,
)


class TestDeriveRatioFromSize:
    def test_standard_16_9(self) -> None:
        assert derive_ratio_from_size("1920x1080") == "16:9"

    def test_standard_9_16(self) -> None:
        assert derive_ratio_from_size("1080x1920") == "9:16"

    def test_square(self) -> None:
        assert derive_ratio_from_size("1024x1024") == "1:1"

    def test_invalid(self) -> None:
        assert derive_ratio_from_size("invalid") is None

    def test_none(self) -> None:
        assert derive_ratio_from_size(None) is None


class TestResolveClosestRatio:
    def test_exact_match(self) -> None:
        result = resolve_closest_ratio(
            requested_ratio="16:9",
            supported_ratios=("16:9", "9:16", "1:1"),
        )
        assert result == "16:9"

    def test_closest_match(self) -> None:
        result = resolve_closest_ratio(
            requested_ratio="15:9",
            supported_ratios=("16:9", "9:16", "1:1"),
        )
        assert result == "16:9"

    def test_from_size(self) -> None:
        result = resolve_closest_ratio(
            requested_size="1920x1080",
            supported_ratios=("16:9", "9:16", "1:1"),
        )
        assert result == "16:9"

    def test_no_supported(self) -> None:
        result = resolve_closest_ratio(
            requested_ratio="4:3",
            supported_ratios=(),
        )
        assert result == "4:3"

    def test_no_request(self) -> None:
        result = resolve_closest_ratio(
            supported_ratios=("16:9",),
        )
        assert result is None


class TestResolveClosestSize:
    def test_exact_area_match(self) -> None:
        sizes = (SizeSpec(1280, 720), SizeSpec(1920, 1080))
        result = resolve_closest_size(
            requested_size="1920x1080",
            supported_sizes=sizes,
        )
        assert result == SizeSpec(1920, 1080)

    def test_closest_by_ratio(self) -> None:
        sizes = (SizeSpec(1280, 720), SizeSpec(720, 1280))
        result = resolve_closest_size(
            requested_ratio="16:9",
            supported_sizes=sizes,
        )
        assert result == SizeSpec(1280, 720)

    def test_no_sizes(self) -> None:
        result = resolve_closest_size(
            requested_size="1920x1080",
            supported_sizes=(),
        )
        assert result is None


class TestResolveClosestDuration:
    def test_exact_match(self) -> None:
        result = resolve_closest_duration(
            requested=6,
            supported_durations=(4, 6, 8),
        )
        assert result == 6

    def test_snap_to_nearest(self) -> None:
        result = resolve_closest_duration(
            requested=5,
            supported_durations=(4, 6, 8),
        )
        assert result == 6

    def test_max_clamp(self) -> None:
        result = resolve_closest_duration(
            requested=100,
            supported_durations=(4, 6, 8),
            max_duration=10,
        )
        assert result == 8

    def test_no_supported(self) -> None:
        result = resolve_closest_duration(
            requested=7,
            supported_durations=(),
        )
        assert result == 7

    def test_none_request(self) -> None:
        result = resolve_closest_duration(
            requested=None,
            supported_durations=(4, 6, 8),
        )
        assert result is None


class TestNormalizeParams:
    def test_no_normalization_needed(self) -> None:
        caps = ModeCapabilities(
            supported_aspect_ratios=("16:9",),
            supported_durations=(6,),
        )
        result = normalize_params(
            caps=caps,
            requested_ratio="16:9",
            requested_duration=6,
        )
        assert result.aspect_ratio == "16:9"
        assert result.duration_seconds == 6
        assert result.records is None

    def test_duration_normalized(self) -> None:
        caps = ModeCapabilities(
            supported_durations=(4, 6, 10),
        )
        result = normalize_params(
            caps=caps,
            requested_duration=7,
        )
        assert result.duration_seconds == 6
        assert result.records is not None
        assert len(result.records) == 1
        assert result.records[0].field == "duration_seconds"

    def test_ratio_normalized(self) -> None:
        caps = ModeCapabilities(
            supported_aspect_ratios=("16:9", "1:1"),
        )
        result = normalize_params(
            caps=caps,
            requested_ratio="15:9",
        )
        assert result.aspect_ratio == "16:9"
        assert result.records is not None
        assert any(r.field == "aspect_ratio" for r in result.records)

    def test_empty_caps(self) -> None:
        caps = ModeCapabilities()
        result = normalize_params(
            caps=caps,
            requested_ratio="16:9",
            requested_duration=5,
        )
        assert result.records is None
