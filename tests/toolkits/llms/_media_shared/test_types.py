"""Tests for _media_shared types."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms._media_shared.types import (
    MediaTaskState,
    ModeCapabilities,
    NormalizationRecord,
    ProviderModeCapabilities,
    SizeSpec,
)


class TestSizeSpec:
    def test_aspect_ratio(self) -> None:
        s = SizeSpec(1920, 1080)
        assert abs(s.aspect_ratio - 16 / 9) < 0.01

    def test_zero_height(self) -> None:
        s = SizeSpec(100, 0)
        assert s.aspect_ratio == 0.0

    def test_frozen(self) -> None:
        s = SizeSpec(100, 100)
        try:
            s.width = 200  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestModeCapabilities:
    def test_defaults_empty(self) -> None:
        caps = ModeCapabilities()
        assert caps.supported_aspect_ratios == ()
        assert caps.supported_sizes == ()
        assert caps.supported_durations == ()
        assert caps.default_duration is None
        assert caps.max_duration_seconds is None


class TestProviderModeCapabilities:
    def test_all_none(self) -> None:
        mc = ProviderModeCapabilities()
        assert mc.generate is None
        assert mc.image_to_video is None
        assert mc.video_to_video is None

    def test_partial(self) -> None:
        mc = ProviderModeCapabilities(
            generate=ModeCapabilities(supported_durations=(4, 6)),
        )
        assert mc.generate is not None
        assert mc.generate.supported_durations == (4, 6)
        assert mc.image_to_video is None


class TestMediaTaskState:
    def test_values(self) -> None:
        assert MediaTaskState.QUEUED == "queued"
        assert MediaTaskState.COMPLETED == "completed"
        assert MediaTaskState.FAILED == "failed"


class TestNormalizationRecord:
    def test_creation(self) -> None:
        r = NormalizationRecord(
            field="duration",
            requested="7",
            applied="6",
            reason="snapped",
        )
        assert r.field == "duration"
        assert r.requested == "7"
        assert r.applied == "6"
