"""Direct unit tests for toolkits.llms.adapters.image_payload_evictor.

Covers the framework-neutral eviction paths (dict fast path, mixed-list
indexed path, stage-1 downsample, stage-2 textify) with small synthetic
images to keep CPU/memory negligible.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
    emergency_evict,
    emergency_evict_from_message_dicts,
)


def _noise_data_url(width: int = 160, height: int = 160, seed: int = 7) -> str:
    """Build a real high-entropy PNG data URL (seeded random noise)."""
    import random

    rng = random.Random(seed)
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    assert pixels is not None
    for x in range(width):
        for y in range(height):
            pixels[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _palette_data_url() -> str:
    """Build a palette-mode PNG to exercise the RGB conversion branch."""
    img = Image.new("P", (64, 64))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _openai_image_part(url: str) -> dict[str, object]:
    return {"type": "image_url", "image_url": {"url": url}}


def _anthropic_image_part(url: str) -> dict[str, object]:
    _header, b64 = url.split(";base64,", 1)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}


class TestDictFastPath:
    def test_empty_list_is_noop(self) -> None:
        assert emergency_evict_from_message_dicts([]) == 0

    def test_under_budget_is_noop(self) -> None:
        messages = [{"role": "user", "content": [_openai_image_part(_noise_data_url(16, 16))]}]
        assert emergency_evict_from_message_dicts(messages, target_bytes=10 * 1024 * 1024) == 0

    def test_non_image_parts_ignored(self) -> None:
        messages = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
        assert emergency_evict_from_message_dicts(messages, target_bytes=1) == 0

    def test_non_base64_url_ignored(self) -> None:
        messages = [{"role": "user", "content": [_openai_image_part("https://example.com/a.png")]}]
        assert emergency_evict_from_message_dicts(messages, target_bytes=1) == 0

    def test_tiny_icon_skipped_in_stage1_but_textified_in_stage2(self) -> None:
        tiny = _openai_image_part(_noise_data_url(8, 8))
        big = _openai_image_part(_noise_data_url(160, 160))
        messages = [
            {"role": "user", "content": [tiny]},
            {"role": "user", "content": [big]},
        ]
        modified = emergency_evict_from_message_dicts(messages, target_bytes=1)
        assert modified >= 1

    def test_anthropic_format_supported(self) -> None:
        messages = [{"role": "user", "content": [_anthropic_image_part(_noise_data_url(160, 160))]}]
        modified = emergency_evict_from_message_dicts(messages, target_bytes=1)
        assert modified >= 1

    def test_stage2_protects_latest_turn(self) -> None:
        old_part = _openai_image_part(_noise_data_url(160, 160))
        new_part = _openai_image_part(_noise_data_url(160, 160))
        messages = [
            {"role": "user", "content": [old_part]},
            {"role": "user", "content": [new_part]},
        ]
        emergency_evict_from_message_dicts(messages, target_bytes=1, force_shrink=True)
        first = messages[0]["content"]
        assert isinstance(first, list)
        assert first[0].get("type") == "text"

    def test_stage1_downsample_preserves_visual(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            _downsample_base64_image,
        )
        from myrm_agent_harness.utils.image_utils import estimate_base64_byte_size

        url = _noise_data_url()
        downsampled = _downsample_base64_image(url)
        assert downsampled is not None and downsampled != url
        # Budget strictly between downsampled and original size: stage-1
        # swap alone satisfies it, stage-2 textify must not trigger.
        target = (estimate_base64_byte_size(url) + estimate_base64_byte_size(downsampled)) // 2
        part = _openai_image_part(url)
        messages = [{"role": "user", "content": [part]}]
        modified = emergency_evict_from_message_dicts(messages, target_bytes=target)
        assert modified >= 1
        content = messages[0]["content"]
        assert isinstance(content, list)
        first = content[0]
        assert isinstance(first, dict)
        inner = first.get("image_url")
        assert isinstance(inner, dict)
        assert str(inner.get("url", "")).startswith("data:image/webp;base64,")

    def test_stage1_anthropic_swap(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            _downsample_base64_image,
        )
        from myrm_agent_harness.utils.image_utils import estimate_base64_byte_size

        url = _noise_data_url()
        downsampled = _downsample_base64_image(url)
        assert downsampled is not None and downsampled != url
        target = (estimate_base64_byte_size(url) + estimate_base64_byte_size(downsampled)) // 2
        part = _anthropic_image_part(url)
        messages = [{"role": "user", "content": [part]}]
        modified = emergency_evict_from_message_dicts(messages, target_bytes=target)
        assert modified >= 1
        content = messages[0]["content"]
        assert isinstance(content, list)
        first = content[0]
        assert isinstance(first, dict)
        source = first.get("source")
        assert isinstance(source, dict)
        assert source.get("media_type") == "image/webp"

    def test_string_content_and_foreign_parts_skipped(self) -> None:
        messages = [
            {"role": "user", "content": "plain string"},
            {"role": "user", "content": ["not-a-dict", 42]},
        ]
        assert emergency_evict_from_message_dicts(messages, target_bytes=1) == 0

    def test_force_shrink_below_budget_still_compacts(self) -> None:
        part = _openai_image_part(_noise_data_url())
        messages = [{"role": "user", "content": [part]}]
        modified = emergency_evict_from_message_dicts(
            messages, target_bytes=10 * 1024 * 1024, force_shrink=True
        )
        assert modified >= 1


class TestHelpers:
    def test_downsample_rejects_non_data_url(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            _downsample_base64_image,
        )

        assert _downsample_base64_image("https://example.com/a.png") is None

    def test_downsample_handles_corrupt_bytes(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            _downsample_base64_image,
        )

        bad = "data:image/png;base64," + base64.b64encode(b"not-an-image").decode("ascii")
        assert _downsample_base64_image(bad) is None

    def test_downsample_converts_palette_mode(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            _downsample_base64_image,
        )

        out = _downsample_base64_image(_palette_data_url())
        assert out is not None

    def test_downsample_converts_grayscale_mode(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            _downsample_base64_image,
        )

        img = Image.new("L", (64, 64))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        assert _downsample_base64_image(url) is not None



    def test_replace_rejects_unknown_shape(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            _replace_image_part,
        )

        assert _replace_image_part({"type": "other"}, "data:image/webp;base64,AAA") is False


class TestUnifiedEntry:
    def test_empty_is_noop(self) -> None:
        assert emergency_evict([]) == 0

    def test_homogeneous_dicts_take_fast_path(self) -> None:
        messages: list[object] = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        assert emergency_evict(messages, target_bytes=1) == 0

    def test_mixed_list_does_not_misindex(self) -> None:
        big = _openai_image_part(_noise_data_url())

        class _Msg:
            def __init__(self, content: object) -> None:
                self.content = content

        messages: list[object] = [
            "not-a-message",
            {"role": "user", "content": [big]},
            _Msg([dict(big)]),
        ]
        modified = emergency_evict(messages, target_bytes=1, force_shrink=True)
        assert modified >= 1

    def test_indexed_path_skips_foreign_parts(self) -> None:
        class _Msg:
            def __init__(self, content: object) -> None:
                self.content = content

        messages: list[object] = [_Msg("plain"), _Msg(["nope", 7])]
        assert emergency_evict(messages, target_bytes=1) == 0

    def test_indexed_path_no_images_returns_zero(self) -> None:
        class _Msg:
            def __init__(self, content: object) -> None:
                self.content = content

        messages: list[object] = [_Msg([{"type": "text", "text": "hi"}])]
        assert emergency_evict(messages, target_bytes=1) == 0

    def test_indexed_path_force_shrink_and_breaks(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            _downsample_base64_image,
        )
        from myrm_agent_harness.utils.image_utils import estimate_base64_byte_size

        class _Msg:
            def __init__(self, content: object) -> None:
                self.content = content

        tiny = _openai_image_part(_noise_data_url(8, 8))
        url = _noise_data_url()
        downsampled = _downsample_base64_image(url)
        assert downsampled is not None and downsampled != url
        target = (estimate_base64_byte_size(url) + estimate_base64_byte_size(downsampled)) // 2
        messages: list[object] = [
            _Msg([dict(tiny)]),
            _Msg([_openai_image_part(url)]),
        ]
        # Below-budget force_shrink compacts; tiny icons skip stage-1.
        assert emergency_evict(messages, target_bytes=10 * 1024 * 1024, force_shrink=True) >= 1
        # Tight budget exercises stage-1 break and stage-2 paths.
        messages2: list[object] = [
            _Msg([_openai_image_part(_noise_data_url(seed=11))]),
            _Msg([_openai_image_part(_noise_data_url(seed=12))]),
        ]
        assert emergency_evict(messages2, target_bytes=target, force_shrink=True) >= 1
