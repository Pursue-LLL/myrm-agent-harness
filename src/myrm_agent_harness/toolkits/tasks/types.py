"""Task type definitions for common task payloads and results.

This module provides dataclasses for common task types (image generation, audio transcription, etc.)
to ensure type safety and consistency across the framework.

[INPUT]
- (none)

[OUTPUT]
- ImageGenerationPayload: Image generation task input parameters.
- ImageData: Single generated image data.
- ImageGenerationResult: Image generation task output.
- AudioTranscriptionPayload: Audio transcription task input parameters.
- AudioTranscriptionResult: Audio transcription task output.

[POS]
Task type definitions for common task payloads and results.
"""

from dataclasses import dataclass, field

# ============================================================================
# Image Generation Tasks
# ============================================================================


@dataclass
class ImageGenerationPayload:
    """Image generation task input parameters."""

    prompt: str  # Text description of desired image
    size: str | None = None  # Image dimensions ("1024x1024", "16:9", etc.)
    quality: str | None = None  # Image quality ("standard", "hd")
    style: str | None = None  # Style option ("vivid", "natural")
    count: int = 1  # Number of images to generate
    reference_image_urls: list[str] | None = None  # Reference images for style transfer

    # Model selection
    model: str | None = None  # Override default model
    provider: str | None = None  # Override default provider

    # Metadata
    usage: str | None = None  # Usage context ("article-inline", "cover", "thumbnail")
    description: str | None = None  # Human-readable description


@dataclass
class ImageData:
    """Single generated image data."""

    url: str  # Image URL or data URI
    width: int | None = None
    height: int | None = None
    mime_type: str = "image/png"
    thumbnail_url: str | None = None  # Optional thumbnail for preview
    size_bytes: int | None = None  # File size in bytes


@dataclass
class ImageGenerationResult:
    """Image generation task output."""

    images: list[ImageData]  # Generated images
    prompt: str  # Final prompt used (may be modified)
    model: str  # Model used for generation
    provider: str  # Provider used
    latency_ms: int | None = None  # Generation time in milliseconds
    metadata: dict[str, object] = field(default_factory=dict)  # Additional metadata


# ============================================================================
# Audio Transcription Tasks (Future)
# ============================================================================


@dataclass
class AudioTranscriptionPayload:
    """Audio transcription task input parameters."""

    audio_url: str  # Audio file URL
    language: str | None = None  # Target language code ("en", "zh", "auto")
    model: str | None = None  # Transcription model
    format: str = "text"  # Output format ("text", "srt", "vtt", "json")
    timestamps: bool = False  # Include word-level timestamps


@dataclass
class AudioTranscriptionResult:
    """Audio transcription task output."""

    text: str  # Transcribed text
    language: str  # Detected language
    duration_seconds: float  # Audio duration
    segments: list[dict] | None = None  # Timestamped segments (if timestamps=True)
    confidence: float | None = None  # Overall confidence score


# ============================================================================
# Video Generation Tasks (Future)
# ============================================================================


@dataclass
class VideoGenerationPayload:
    """Video generation task input parameters."""

    prompt: str  # Text description or script
    duration_seconds: int  # Video duration
    resolution: str = "1080p"  # Video resolution
    fps: int = 30  # Frames per second
    model: str | None = None


@dataclass
class VideoGenerationResult:
    """Video generation task output."""

    video_url: str  # Generated video URL
    duration_seconds: int
    resolution: str
    thumbnail_url: str | None = None
    size_bytes: int | None = None


# ============================================================================
# Batch Processing Tasks
# ============================================================================


@dataclass
class BatchProcessingPayload:
    """Batch processing task input parameters."""

    operation: str  # Operation type ("resize", "convert", "compress", etc.)
    input_urls: list[str]  # Input file URLs
    params: dict[str, object]  # Operation-specific parameters


@dataclass
class BatchProcessingResult:
    """Batch processing task output."""

    output_urls: list[str]  # Processed file URLs
    success_count: int
    failed_count: int
    failures: list[dict] | None = None  # Failed items with error details


# ============================================================================
# Utility Functions
# ============================================================================


def get_payload_class(task_type: str) -> type | None:
    """Get payload dataclass for task type."""
    mapping = {
        "image_generate": ImageGenerationPayload,
        "audio_transcribe": AudioTranscriptionPayload,
        "video_generate": VideoGenerationPayload,
        "batch_process": BatchProcessingPayload,
    }
    return mapping.get(task_type)


def get_result_class(task_type: str) -> type | None:
    """Get result dataclass for task type."""
    mapping = {
        "image_generate": ImageGenerationResult,
        "audio_transcribe": AudioTranscriptionResult,
        "video_generate": VideoGenerationResult,
        "batch_process": BatchProcessingResult,
    }
    return mapping.get(task_type)


__all__ = [
    # Audio transcription
    "AudioTranscriptionPayload",
    "AudioTranscriptionResult",
    # Batch processing
    "BatchProcessingPayload",
    "BatchProcessingResult",
    "ImageData",
    # Image generation
    "ImageGenerationPayload",
    "ImageGenerationResult",
    # Video generation
    "VideoGenerationPayload",
    "VideoGenerationResult",
    # Utilities
    "get_payload_class",
    "get_result_class",
]
