"""Tests for extended media utilities (video/audio support) in image_utils."""

from __future__ import annotations

from myrm_agent_harness.utils.image_utils import (
    content_has_media,
    is_media_content_item,
    strip_all_media_from_content,
)


class TestIsMediaContentItem:
    """Test is_media_content_item covers all media types."""

    def test_image_url(self) -> None:
        assert is_media_content_item({"type": "image_url"}) is True

    def test_image(self) -> None:
        assert is_media_content_item({"type": "image"}) is True

    def test_input_image(self) -> None:
        assert is_media_content_item({"type": "input_image"}) is True

    def test_video_url(self) -> None:
        assert is_media_content_item({"type": "video_url"}) is True

    def test_video(self) -> None:
        assert is_media_content_item({"type": "video"}) is True

    def test_input_video(self) -> None:
        assert is_media_content_item({"type": "input_video"}) is True

    def test_audio_url(self) -> None:
        assert is_media_content_item({"type": "audio_url"}) is True

    def test_audio(self) -> None:
        assert is_media_content_item({"type": "audio"}) is True

    def test_input_audio(self) -> None:
        assert is_media_content_item({"type": "input_audio"}) is True

    def test_text_not_media(self) -> None:
        assert is_media_content_item({"type": "text"}) is False

    def test_non_dict(self) -> None:
        assert is_media_content_item("hello") is False

    def test_custom_type(self) -> None:
        assert is_media_content_item({"type": "custom"}) is False


class TestContentHasMedia:
    """Test content_has_media."""

    def test_string_content(self) -> None:
        assert content_has_media("hello") is False

    def test_list_with_image(self) -> None:
        assert content_has_media([{"type": "image_url"}]) is True

    def test_list_with_video(self) -> None:
        assert content_has_media([{"type": "video_url"}]) is True

    def test_list_with_audio(self) -> None:
        assert content_has_media([{"type": "audio_url"}]) is True

    def test_list_without_media(self) -> None:
        assert content_has_media([{"type": "text", "text": "hi"}]) is False

    def test_mixed_content(self) -> None:
        content = [
            {"type": "text", "text": "look"},
            {"type": "video", "data": "xyz"},
        ]
        assert content_has_media(content) is True


class TestStripAllMediaFromContent:
    """Test strip_all_media_from_content."""

    def test_string_passthrough(self) -> None:
        assert strip_all_media_from_content("hello") == "hello"

    def test_strips_image(self) -> None:
        content: list[object] = [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        result = strip_all_media_from_content(content)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "look"}
        assert result[1]["type"] == "text"
        assert "does not support" in result[1]["text"].lower()

    def test_strips_video(self) -> None:
        content: list[object] = [
            {"type": "video_url", "video_url": {"url": "https://v.mp4"}},
        ]
        result = strip_all_media_from_content(content)
        assert isinstance(result, list)
        assert result[0]["type"] == "text"

    def test_strips_audio(self) -> None:
        content: list[object] = [
            {"type": "audio", "data": "xyz"},
        ]
        result = strip_all_media_from_content(content)
        assert isinstance(result, list)
        assert result[0]["type"] == "text"

    def test_strips_all_media_types_at_once(self) -> None:
        content: list[object] = [
            {"type": "text", "text": "mixed"},
            {"type": "image_url", "image_url": {"url": "base64..."}},
            {"type": "video_url", "video_url": {"url": "https://v.mp4"}},
            {"type": "audio_url", "audio_url": {"url": "https://a.mp3"}},
            {"type": "input_image", "source": {"data": "abc"}},
            {"type": "input_video", "source": {"data": "def"}},
            {"type": "input_audio", "source": {"data": "ghi"}},
        ]
        result = strip_all_media_from_content(content)
        assert isinstance(result, list)
        assert len(result) == 7
        assert result[0] == {"type": "text", "text": "mixed"}
        for i in range(1, 7):
            assert result[i]["type"] == "text"

    def test_no_media_returns_original(self) -> None:
        content: list[object] = [
            {"type": "text", "text": "hello"},
            {"type": "custom", "data": 123},
        ]
        result = strip_all_media_from_content(content)
        assert result is content

    def test_preserves_text_items(self) -> None:
        content: list[object] = [
            {"type": "text", "text": "first"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "text", "text": "second"},
        ]
        result = strip_all_media_from_content(content)
        assert isinstance(result, list)
        assert result[0] == {"type": "text", "text": "first"}
        assert result[2] == {"type": "text", "text": "second"}
