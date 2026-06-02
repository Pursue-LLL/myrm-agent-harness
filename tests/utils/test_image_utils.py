"""Tests for image content utilities (base64 overflow prevention)."""

from __future__ import annotations

import base64

from langchain_core.messages import HumanMessage

from myrm_agent_harness.utils.image_utils import (
    IMAGE_TOKEN_ESTIMATE,
    content_has_images,
    content_has_media,
    estimate_base64_byte_size,
    estimate_image_tokens_in_content,
    get_image_url,
    is_base64_data_url,
    is_image_content_item,
    is_media_content_item,
    strip_all_media_from_content,
    strip_images_from_content,
)


class TestIsBase64DataUrl:
    def test_valid_png(self) -> None:
        assert is_base64_data_url("data:image/png;base64,iVBOR...") is True

    def test_valid_jpeg(self) -> None:
        assert is_base64_data_url("data:image/jpeg;base64,/9j/4AAQ...") is True

    def test_regular_url(self) -> None:
        assert is_base64_data_url("https://example.com/image.png") is False

    def test_empty_string(self) -> None:
        assert is_base64_data_url("") is False

    def test_non_string(self) -> None:
        assert is_base64_data_url(123) is False  # type: ignore[arg-type]


class TestGetImageUrl:
    def test_extracts_url(self) -> None:
        assert get_image_url({"type": "image_url", "image_url": {"url": "https://a.com/b.png"}}) == "https://a.com/b.png"

    def test_missing_image_url_key(self) -> None:
        assert get_image_url({"type": "image_url"}) == ""

    def test_image_url_not_dict(self) -> None:
        assert get_image_url({"type": "image_url", "image_url": "not_a_dict"}) == ""

    def test_empty_url(self) -> None:
        assert get_image_url({"type": "image_url", "image_url": {"url": ""}}) == ""


class TestIsImageContentItem:
    def test_image_url_item(self) -> None:
        assert is_image_content_item({"type": "image_url", "image_url": {"url": "..."}}) is True

    def test_image_item(self) -> None:
        assert is_image_content_item({"type": "image", "base64": "abc", "mime_type": "image/jpeg"}) is True

    def test_input_image_item(self) -> None:
        assert is_image_content_item({"type": "input_image", "source": {"data": "abc"}}) is True

    def test_text_item(self) -> None:
        assert is_image_content_item({"type": "text", "text": "hello"}) is False

    def test_non_dict(self) -> None:
        assert is_image_content_item("hello") is False


class TestEstimateBase64ByteSize:
    def test_known_size(self) -> None:
        raw = b"x" * 1000
        b64 = base64.b64encode(raw).decode("ascii")
        url = f"data:image/png;base64,{b64}"
        estimated = estimate_base64_byte_size(url)
        assert abs(estimated - 1000) <= 3

    def test_non_data_url(self) -> None:
        assert estimate_base64_byte_size("https://example.com") == 0

    def test_malformed_base64_url(self) -> None:
        assert estimate_base64_byte_size("data:image/png;base64,") == 0


class TestEstimateImageTokensInContent:
    def test_string_content(self) -> None:
        assert estimate_image_tokens_in_content("hello world") == 0

    def test_content_with_one_image(self) -> None:
        content: list[object] = [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        assert estimate_image_tokens_in_content(content) == IMAGE_TOKEN_ESTIMATE

    def test_content_with_multiple_images(self) -> None:
        content: list[object] = [
            {"type": "image_url", "image_url": {"url": "..."}},
            {"type": "image_url", "image_url": {"url": "..."}},
        ]
        assert estimate_image_tokens_in_content(content) == IMAGE_TOKEN_ESTIMATE * 2

    def test_no_images(self) -> None:
        content: list[object] = [
            {"type": "text", "text": "Just text"},
        ]
        assert estimate_image_tokens_in_content(content) == 0

    def test_type_image(self) -> None:
        content: list[object] = [
            {"type": "image", "base64": "abc", "mime_type": "image/jpeg"},
        ]
        assert estimate_image_tokens_in_content(content) == IMAGE_TOKEN_ESTIMATE

    def test_type_input_image(self) -> None:
        content: list[object] = [
            {"type": "input_image", "source": {"data": "abc"}},
        ]
        assert estimate_image_tokens_in_content(content) == IMAGE_TOKEN_ESTIMATE


class TestStripImagesFromContent:
    def test_string_passthrough(self) -> None:
        assert strip_images_from_content("hello") == "hello"

    def test_strips_base64_image(self) -> None:
        content: list[object] = [
            {"type": "text", "text": "Look at this:"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
        ]
        result = strip_images_from_content(content)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "Look at this:"}
        assert result[1] == {"type": "text", "text": "[Image removed during context compression]"}

    def test_strips_url_image(self) -> None:
        content: list[object] = [
            {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}},
        ]
        result = strip_images_from_content(content)
        assert isinstance(result, list)
        assert result[0]["type"] == "text"
        assert "https://example.com/photo.jpg" in result[0]["text"]

    def test_strips_type_image(self) -> None:
        """LangChain create_image_block produces type='image'."""
        content: list[object] = [
            {"type": "text", "text": "Screenshot taken"},
            {"type": "image", "base64": "x" * 1000, "mime_type": "image/jpeg"},
        ]
        result = strip_images_from_content(content)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "Screenshot taken"}
        assert result[1] == {"type": "text", "text": "[Image removed during context compression]"}

    def test_strips_type_input_image(self) -> None:
        """Anthropic format uses type='input_image'."""
        content: list[object] = [
            {"type": "input_image", "source": {"data": "x" * 1000}},
        ]
        result = strip_images_from_content(content)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == {"type": "text", "text": "[Image removed during context compression]"}

    def test_strips_mixed_image_types(self) -> None:
        """All three image types in one content list."""
        content: list[object] = [
            {"type": "text", "text": "hello"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "image", "base64": "xyz", "mime_type": "image/png"},
            {"type": "input_image", "source": {"data": "def"}},
        ]
        result = strip_images_from_content(content)
        assert isinstance(result, list)
        assert len(result) == 4
        assert result[0] == {"type": "text", "text": "hello"}
        for i in range(1, 4):
            assert result[i]["type"] == "text"
            assert "removed" in result[i]["text"].lower()

    def test_strips_image_url_no_url_field(self) -> None:
        """image_url item with missing url should use compressed placeholder."""
        content: list[object] = [
            {"type": "image_url", "image_url": {}},
        ]
        result = strip_images_from_content(content)
        assert isinstance(result, list)
        assert result[0] == {"type": "text", "text": "[Image removed during context compression]"}

    def test_preserves_non_image_items(self) -> None:
        content: list[object] = [
            {"type": "text", "text": "hello"},
            {"type": "custom", "data": 123},
        ]
        result = strip_images_from_content(content)
        assert result == content


class TestContentHasImages:
    def test_string_no_images(self) -> None:
        assert content_has_images("hello") is False

    def test_list_with_image_url(self) -> None:
        assert content_has_images([{"type": "image_url"}]) is True

    def test_list_with_type_image(self) -> None:
        assert content_has_images([{"type": "image", "base64": "abc"}]) is True

    def test_list_with_input_image(self) -> None:
        assert content_has_images([{"type": "input_image"}]) is True

    def test_list_without_image(self) -> None:
        assert content_has_images([{"type": "text"}]) is False


class TestTokenEstimationIntegration:
    """Test that estimate_messages_tokens correctly handles images."""

    def test_image_uses_fixed_estimate(self) -> None:
        from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

        b64 = base64.b64encode(b"x" * 100_000).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"

        msg_with_image = HumanMessage(
            content=[
                {"type": "text", "text": "What is this?"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        )
        msg_text_only = HumanMessage(content="What is this?")

        tokens_with_image = estimate_messages_tokens([msg_with_image])
        tokens_text_only = estimate_messages_tokens([msg_text_only])

        image_overhead = tokens_with_image - tokens_text_only
        assert abs(image_overhead - IMAGE_TOKEN_ESTIMATE) < 10

class TestMediaContentUtils:
    def test_is_media_content_item(self) -> None:
        assert is_media_content_item({"type": "image_url"}) is True
        assert is_media_content_item({"type": "video_url"}) is True
        assert is_media_content_item({"type": "audio_url"}) is True
        assert is_media_content_item({"type": "text"}) is False
        assert is_media_content_item("string") is False

    def test_content_has_media(self) -> None:
        assert content_has_media("string") is False
        assert content_has_media([{"type": "text"}]) is False
        assert content_has_media([{"type": "text"}, {"type": "video_url"}]) is True

    def test_strip_all_media_from_content(self) -> None:
        assert strip_all_media_from_content("string") == "string"

        content = [
            {"type": "text", "text": "hello"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            {"type": "video_url", "video_url": {"url": "..."}}
        ]
        stripped = strip_all_media_from_content(content)
        assert len(stripped) == 3
        assert stripped[0] == {"type": "text", "text": "hello"}
        assert stripped[1]["type"] == "text"
        assert "Media removed" in stripped[1]["text"]
        assert stripped[2]["type"] == "text"
        assert "Media removed" in stripped[2]["text"]
