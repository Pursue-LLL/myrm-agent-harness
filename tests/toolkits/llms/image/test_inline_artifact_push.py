"""Tests for artifact push callback in ImageGenerationTools."""

from myrm_agent_harness.core.artifacts.constants import ArtifactType
from myrm_agent_harness.toolkits.llms.image.generator import ImageResult
from myrm_agent_harness.toolkits.llms.image.image_engine import ImageGenerationTools
from myrm_agent_harness.toolkits.llms.image.models import ImageGenerationConfig

_DUMMY_CONFIG = ImageGenerationConfig(api_keys={"openai": "test-key"})


def _make_tools(captured: list[tuple[str, str, ArtifactType, str]]) -> ImageGenerationTools:
    """Build ImageGenerationTools with a capturing callback."""

    def _capture(filename: str, url: str, art_type: ArtifactType, mime: str) -> None:
        captured.append((filename, url, art_type, mime))

    return ImageGenerationTools(_DUMMY_CONFIG, on_artifact_created=_capture)


class TestPushArtifactCallback:
    """Tests for ImageGenerationTools._push_artifact via on_artifact_created callback."""

    def test_push_with_url(self):
        captured: list[tuple[str, str, ArtifactType, str]] = []
        tools = _make_tools(captured)
        result = ImageResult(
            url="https://oai.com/img.png",
            b64_json=None,
            revised_prompt=None,
            model="dall-e-3",
            latency_ms=1200.0,
        )
        tools._push_artifact(result)

        assert len(captured) == 1
        assert captured[0][1] == "https://oai.com/img.png"
        assert captured[0][0] == "generated_dall-e-3.png"
        assert captured[0][2] == ArtifactType.IMAGE

    def test_push_with_persisted_url_preferred(self):
        captured: list[tuple[str, str, ArtifactType, str]] = []
        tools = _make_tools(captured)
        result = ImageResult(
            url="https://oai.com/temporary.png",
            b64_json=None,
            revised_prompt=None,
            model="dall-e-3",
            persisted_url="https://storage.example.com/permanent.png",
        )
        tools._push_artifact(result)

        assert len(captured) == 1
        assert captured[0][1] == "https://storage.example.com/permanent.png"

    def test_no_push_when_no_url(self):
        captured: list[tuple[str, str, ArtifactType, str]] = []
        tools = _make_tools(captured)
        result = ImageResult(
            url=None,
            b64_json="base64data...",
            revised_prompt=None,
            model="stability-ai/sdxl",
        )
        tools._push_artifact(result)

        assert len(captured) == 0

    def test_no_push_when_both_none(self):
        captured: list[tuple[str, str, ArtifactType, str]] = []
        tools = _make_tools(captured)
        result = ImageResult(
            url=None,
            b64_json=None,
            revised_prompt=None,
            model="test-model",
        )
        tools._push_artifact(result)

        assert len(captured) == 0

    def test_no_error_without_callback(self):
        tools = ImageGenerationTools(_DUMMY_CONFIG)
        result = ImageResult(
            url="https://example.com/test.png",
            b64_json=None,
            revised_prompt=None,
            model="dall-e-3",
        )
        tools._push_artifact(result)

    def test_b64_with_persisted_url_pushes(self):
        captured: list[tuple[str, str, ArtifactType, str]] = []
        tools = _make_tools(captured)
        result = ImageResult(
            url=None,
            b64_json="base64data...",
            revised_prompt=None,
            model="dall-e-2",
            persisted_url="https://storage.example.com/cb.png",
        )
        tools._push_artifact(result)

        assert len(captured) == 1
        assert captured[0][1] == "https://storage.example.com/cb.png"

    def test_model_name_in_filename(self):
        captured: list[tuple[str, str, ArtifactType, str]] = []
        tools = _make_tools(captured)
        result = ImageResult(
            url="https://x.com/img.png",
            b64_json=None,
            revised_prompt=None,
            model="gpt-image-1",
        )
        tools._push_artifact(result)

        assert captured[0][0] == "generated_gpt-image-1.png"
