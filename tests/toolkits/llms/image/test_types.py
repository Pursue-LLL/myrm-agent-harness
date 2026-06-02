"""Tests for image generation types: ModelProfile and profile registry."""

import pytest

from myrm_agent_harness.toolkits.llms.image.types import (
    BUILTIN_PROFILES,
    ModelProfile,
    get_profile,
    list_profiles,
    register_profile,
)


class TestModelProfile:
    """Tests for ModelProfile dataclass."""

    def test_default_values(self) -> None:
        p = ModelProfile(name="test-model")
        assert p.name == "test-model"
        assert p.api_key_provider == "openai"
        assert p.max_count == 1
        assert p.supports_edit is False
        assert p.max_input_images == 0
        assert p.allowed_sizes == frozenset()
        assert p.max_prompt_length == 4000
        assert p.allowed_output_formats == frozenset({"png"})

    def test_custom_api_key_provider(self) -> None:
        p = ModelProfile(name="custom", api_key_provider="gemini")
        assert p.api_key_provider == "gemini"

    def test_frozen(self) -> None:
        p = ModelProfile(name="test")
        with pytest.raises(AttributeError):
            p.name = "other"  # type: ignore[misc]

    def test_to_dict_minimal(self) -> None:
        p = ModelProfile(name="test")
        d = p.to_dict()
        assert d["name"] == "test"
        assert d["api_key_provider"] == "openai"
        assert d["max_count"] == 1
        assert d["supports_edit"] is False
        assert "allowed_sizes" not in d
        assert "max_input_images" not in d

    def test_to_dict_includes_api_key_provider(self) -> None:
        p = ModelProfile(name="gemini-model", api_key_provider="gemini")
        d = p.to_dict()
        assert d["api_key_provider"] == "gemini"

    def test_to_dict_full(self) -> None:
        p = ModelProfile(
            name="full",
            api_key_provider="together_ai",
            max_count=4,
            supports_edit=True,
            max_input_images=2,
            allowed_sizes=frozenset({"1024x1024", "512x512"}),
            allowed_aspect_ratios=frozenset({"1:1", "16:9"}),
            allowed_output_formats=frozenset({"png", "jpeg"}),
        )
        d = p.to_dict()
        assert d["api_key_provider"] == "together_ai"
        assert d["max_input_images"] == 2
        assert sorted(d["allowed_sizes"]) == ["1024x1024", "512x512"]
        assert set(d["allowed_aspect_ratios"]) == {"1:1", "16:9"}


class TestProfileRegistry:
    """Tests for profile registration and lookup."""

    def test_builtin_profiles_exist(self) -> None:
        assert "dall-e-3" in BUILTIN_PROFILES
        assert "dall-e-2" in BUILTIN_PROFILES
        assert "gpt-image-1" in BUILTIN_PROFILES
        assert "gemini/imagen-3.0-generate-002" in BUILTIN_PROFILES
        assert "flux/schnell" in BUILTIN_PROFILES
        assert "flux/pro" in BUILTIN_PROFILES
        assert "stability/stable-diffusion-xl" in BUILTIN_PROFILES

    def test_builtin_count(self) -> None:
        assert len(BUILTIN_PROFILES) == 7

    def test_get_profile_known(self) -> None:
        p = get_profile("dall-e-3")
        assert p is not None
        assert p.name == "dall-e-3"
        assert p.max_count == 1

    def test_get_profile_unknown(self) -> None:
        assert get_profile("unknown-model-xyz") is None

    def test_register_custom_profile(self) -> None:
        custom = ModelProfile(name="my-custom-model", max_count=8)
        register_profile(custom)
        found = get_profile("my-custom-model")
        assert found is not None
        assert found.max_count == 8

    def test_list_profiles_sorted(self) -> None:
        profiles = list_profiles()
        names = [p.name for p in profiles]
        assert names == sorted(names)
        assert len(profiles) >= len(BUILTIN_PROFILES)

    def test_dalle2_supports_edit(self) -> None:
        p = get_profile("dall-e-2")
        assert p is not None
        assert p.supports_edit is True
        assert p.max_input_images == 1

    def test_gpt_image_1_capabilities(self) -> None:
        p = get_profile("gpt-image-1")
        assert p is not None
        assert p.supports_edit is True
        assert "auto" in p.allowed_sizes
        assert p.max_prompt_length == 32000

    @pytest.mark.parametrize(
        "model,expected_provider",
        [
            ("dall-e-3", "openai"),
            ("dall-e-2", "openai"),
            ("gpt-image-1", "openai"),
            ("gemini/imagen-3.0-generate-002", "gemini"),
            ("flux/schnell", "together_ai"),
            ("flux/pro", "together_ai"),
            ("stability/stable-diffusion-xl", "stability"),
        ],
    )
    def test_api_key_provider_per_model(self, model: str, expected_provider: str) -> None:
        p = get_profile(model)
        assert p is not None
        assert p.api_key_provider == expected_provider

    def test_gemini_imagen_capabilities(self) -> None:
        p = get_profile("gemini/imagen-3.0-generate-002")
        assert p is not None
        assert p.max_count == 4
        assert "16:9" in p.allowed_aspect_ratios

    def test_flux_schnell_capabilities(self) -> None:
        p = get_profile("flux/schnell")
        assert p is not None
        assert p.max_prompt_length == 2048

    def test_stability_sdxl_capabilities(self) -> None:
        p = get_profile("stability/stable-diffusion-xl")
        assert p is not None
        assert p.max_count == 4
        assert "1024x1024" in p.allowed_sizes
