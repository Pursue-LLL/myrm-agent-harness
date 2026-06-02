"""Image generation model profiles and capability declarations.

[OUTPUT]
- ModelProfile: Capability boundary for an image generation model
- BUILTIN_PROFILES: Pre-registered profiles for common models
- get_profile / register_profile: Lookup and custom registration

[POS]
Defines the capability schema for image generation models.
Enables pre-call validation (reject invalid requests before API call)
and model discovery (Agent can list available models and their abilities).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Capability boundary of a single image generation model.

    All fields describe *what the model supports*.  The validator
    uses these constraints to reject invalid requests before they
    hit the remote API, saving cost and latency.
    """

    name: str
    api_key_provider: str = "openai"
    max_count: int = 1
    supports_edit: bool = False
    max_input_images: int = 0
    allowed_sizes: frozenset[str] = frozenset()
    allowed_aspect_ratios: frozenset[str] = frozenset()
    max_prompt_length: int = 4000
    allowed_output_formats: frozenset[str] = frozenset({"png"})

    def to_dict(self) -> dict[str, object]:
        """Serialise for the ``action=list`` tool response."""
        d: dict[str, object] = {
            "name": self.name,
            "api_key_provider": self.api_key_provider,
            "max_count": self.max_count,
            "supports_edit": self.supports_edit,
            "max_prompt_length": self.max_prompt_length,
        }
        if self.max_input_images:
            d["max_input_images"] = self.max_input_images
        if self.allowed_sizes:
            d["allowed_sizes"] = sorted(self.allowed_sizes)
        if self.allowed_aspect_ratios:
            d["allowed_aspect_ratios"] = sorted(self.allowed_aspect_ratios)
        if self.allowed_output_formats:
            d["allowed_output_formats"] = sorted(self.allowed_output_formats)
        return d


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

_DALLE3_SIZES = frozenset({"1024x1024", "1024x1792", "1792x1024"})
_DALLE2_SIZES = frozenset({"256x256", "512x512", "1024x1024"})
_GPT_IMAGE_SIZES = frozenset({"1024x1024", "1024x1536", "1536x1024", "auto"})

BUILTIN_PROFILES: dict[str, ModelProfile] = {
    "dall-e-3": ModelProfile(
        name="dall-e-3",
        max_count=1,
        allowed_sizes=_DALLE3_SIZES,
        max_prompt_length=4000,
        allowed_output_formats=frozenset({"png"}),
    ),
    "dall-e-2": ModelProfile(
        name="dall-e-2",
        max_count=10,
        supports_edit=True,
        max_input_images=1,
        allowed_sizes=_DALLE2_SIZES,
        max_prompt_length=1000,
        allowed_output_formats=frozenset({"png"}),
    ),
    "gpt-image-1": ModelProfile(
        name="gpt-image-1",
        max_count=1,
        supports_edit=True,
        max_input_images=1,
        allowed_sizes=_GPT_IMAGE_SIZES,
        max_prompt_length=32000,
        allowed_output_formats=frozenset({"png", "jpeg", "webp"}),
    ),
    "gemini/imagen-3.0-generate-002": ModelProfile(
        name="gemini/imagen-3.0-generate-002",
        api_key_provider="gemini",
        max_count=4,
        allowed_sizes=frozenset(),
        allowed_aspect_ratios=frozenset({"1:1", "3:4", "4:3", "9:16", "16:9"}),
        max_prompt_length=5000,
        allowed_output_formats=frozenset({"png", "jpeg"}),
    ),
    "flux/schnell": ModelProfile(
        name="flux/schnell",
        api_key_provider="together_ai",
        max_count=1,
        allowed_sizes=frozenset(),
        max_prompt_length=2048,
        allowed_output_formats=frozenset({"png", "jpeg"}),
    ),
    "flux/pro": ModelProfile(
        name="flux/pro",
        api_key_provider="together_ai",
        max_count=1,
        allowed_sizes=frozenset(),
        max_prompt_length=2048,
        allowed_output_formats=frozenset({"png", "jpeg"}),
    ),
    "stability/stable-diffusion-xl": ModelProfile(
        name="stability/stable-diffusion-xl",
        api_key_provider="stability",
        max_count=4,
        allowed_sizes=frozenset({"1024x1024", "1152x896", "896x1152"}),
        max_prompt_length=2000,
        allowed_output_formats=frozenset({"png"}),
    ),
}

# Runtime registry (copy of built-ins + user-registered profiles)
_registry: dict[str, ModelProfile] = copy.copy(BUILTIN_PROFILES)


def register_profile(profile: ModelProfile) -> None:
    """Register a custom model profile (or override a built-in)."""
    _registry[profile.name] = profile


def get_profile(model: str) -> ModelProfile | None:
    """Look up a model profile by exact name.

    Returns ``None`` for unknown models (validation will be skipped).
    """
    return _registry.get(model)


def list_profiles() -> list[ModelProfile]:
    """Return all registered profiles, sorted by name."""
    return sorted(_registry.values(), key=lambda p: p.name)
