"""Tests for image async-job payload/result DTOs."""

import pytest

from myrm_agent_harness.toolkits.llms.media_task_types import (
    TASK_TYPE_IMAGE_GENERATE,
    ImageGenerationPayload,
    ImageGenerationResult,
    get_media_task_payload_class,
    get_media_task_result_class,
)


def test_get_media_task_payload_class_image_generate() -> None:
    assert get_media_task_payload_class(TASK_TYPE_IMAGE_GENERATE) is ImageGenerationPayload


def test_get_media_task_result_class_image_generate() -> None:
    assert get_media_task_result_class(TASK_TYPE_IMAGE_GENERATE) is ImageGenerationResult


@pytest.mark.parametrize("task_type", ["unknown_type", "audio_transcribe", "video_generate"])
def test_get_media_task_class_unknown(task_type: str) -> None:
    assert get_media_task_payload_class(task_type) is None
    assert get_media_task_result_class(task_type) is None
