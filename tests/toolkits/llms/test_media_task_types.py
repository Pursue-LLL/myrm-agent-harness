"""Tests for media task type payload/result mappings."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.media_task_types import (
    TASK_TYPE_IMAGE_GENERATE,
    TASK_TYPE_VIDEO_GENERATE,
    ImageGenerationPayload,
    ImageGenerationResult,
    VideoGenerationPayload,
    VideoGenerationResult,
    get_media_task_payload_class,
    get_media_task_result_class,
)


def test_media_task_payload_mapping_includes_image_and_video() -> None:
    assert get_media_task_payload_class(TASK_TYPE_IMAGE_GENERATE) is ImageGenerationPayload
    assert get_media_task_payload_class(TASK_TYPE_VIDEO_GENERATE) is VideoGenerationPayload


def test_media_task_result_mapping_includes_image_and_video() -> None:
    assert get_media_task_result_class(TASK_TYPE_IMAGE_GENERATE) is ImageGenerationResult
    assert get_media_task_result_class(TASK_TYPE_VIDEO_GENERATE) is VideoGenerationResult


def test_media_task_mapping_unknown_type_returns_none() -> None:
    assert get_media_task_payload_class("unknown") is None
    assert get_media_task_result_class("unknown") is None


@pytest.mark.parametrize("task_type", ["unknown_type", "audio_transcribe"])
def test_get_media_task_class_unknown(task_type: str) -> None:
    assert get_media_task_payload_class(task_type) is None
    assert get_media_task_result_class(task_type) is None
