from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    FailoverAttempt,
    ImageGenerationConfig,
    ImageGenerationError,
    ImageResult,
    MediaCallback,
    MediaMeta,
)
from .types import ModelProfile, get_profile, list_profiles, register_profile
from .validator import ValidationError

if TYPE_CHECKING:
    from .async_image_engine import AsyncImageGenerationTools
    from .generator import ImageGenerator
    from .image_engine import ImageGenerationTools
    from .validator import ImageValidator

__all__ = [
    "AsyncImageGenerationTools",
    "FailoverAttempt",
    "ImageGenerationConfig",
    "ImageGenerationError",
    "ImageGenerationTools",
    "ImageGenerator",
    "ImageResult",
    "ImageValidator",
    "MediaCallback",
    "MediaMeta",
    "ModelProfile",
    "ValidationError",
    "get_profile",
    "list_profiles",
    "register_profile",
]

_LAZY_SYMBOLS = {"AsyncImageGenerationTools", "ImageGenerator", "ImageGenerationTools", "ImageValidator"}

if __debug__:
    _extra = _LAZY_SYMBOLS - set(__all__)
    if _extra:
        raise RuntimeError(f"llms.image: lazy symbols not in __all__: {_extra}")


def __getattr__(name: str) -> type:
    """Lazy load heavy classes on first access."""
    if name == "AsyncImageGenerationTools":
        from .async_image_engine import AsyncImageGenerationTools

        globals()[name] = AsyncImageGenerationTools
        return AsyncImageGenerationTools
    if name == "ImageGenerator":
        from .generator import ImageGenerator

        globals()[name] = ImageGenerator
        return ImageGenerator
    if name == "ImageGenerationTools":
        from .image_engine import ImageGenerationTools

        globals()[name] = ImageGenerationTools
        return ImageGenerationTools
    if name == "ImageValidator":
        from .validator import ImageValidator

        globals()[name] = ImageValidator
        return ImageValidator

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
