"""Image compression tool for jpg/jpeg/png formats.

[INPUT]

[OUTPUT]
- bytes | None: compressed image bytes if output_path is None

[POS]
Pure image compression utility. Supports jpg/jpeg/png formats.
Uses Pillow for jpg/jpeg/webp, imagequant for PNG (with Pillow fallback).
Also exposes ``compress_if_needed`` — responsive send-time compression with
animated GIF/WebP protection and fail-safe fallback to the original bytes.
``MAX_DECODE_PIXELS`` bounds Pillow's decode guard so decompression-bomb
images fail fast instead of exhausting memory.
"""

from __future__ import annotations

import io
import logging
import typing
from pathlib import Path
from typing import BinaryIO

from PIL import Image

logger = logging.getLogger(__name__)

# SSOT — send-time compression defaults shared by MediaResolver and upload flows.
# ``trigger_bytes`` is measured in base64 space to mirror provider per-image
# ceilings (Claude API 10 MiB, Anthropic on Bedrock/Vertex & OpenAI 5 MiB,
# Groq 4 MiB): raw bytes inflate ~4/3 when base64-embedded, so a raw-byte
# comparison under a 4 MiB ceiling would let a 5.3 MiB base64 payload through.
# Mirrors hermes-agent's base64-space embed cap (_EMBED_TARGET_BYTES = 4 MiB),
# while keeping 2048px fidelity for vision analysis.
SEND_COMPRESS_MAX_DIMENSION = 2048
SEND_COMPRESS_QUALITY = 0.75
SEND_COMPRESS_TRIGGER_BYTES = 4 * 1024 * 1024

# Decode guard — bounds Pillow's built-in decompression-bomb protection.
# ``Image.MAX_IMAGE_PIXELS`` is a process-wide setting: assigning ``None``
# silently disables the guard for every Pillow decode in the process, so a
# tiny file declaring a huge canvas would be decoded in full. Bounding it
# keeps legitimate images decodable (Anthropic caps at 8000px per side
# ≈ 64 MP) while bombs raise DecompressionBombError at ``Image.open`` before
# any pixel allocation.
MAX_DECODE_PIXELS = 80_000_000


class ImageCompressor:
    """Image compression tool supporting jpg/jpeg/png formats.

    Uses:
    - Pillow for jpg/jpeg/webp
    - imagequant for PNG (with Pillow fallback)
    """

    SUPPORTED_FORMATS: typing.ClassVar[set[str]] = {".jpg", ".jpeg", ".png"}

    def compress(
        self,
        input_path: str | Path | BinaryIO | bytes,
        output_path: str | Path | None = None,
        quality: float = 0.8,
        max_dimension: int | None = 2048,
        output_format: str | None = None,
    ) -> bytes | None:
        """Compress image.

        Args:
            input_path: Input image path, file object, or raw bytes
            output_path: Output image path, if None returns bytes
            quality: Compression quality (0.0-1.0), 0=lowest, 1=highest
            max_dimension: Maximum dimension (width or height). If exceeded, image is downsampled.
            output_format: Optional forced output format ("jpeg"/"png"/"webp"). Defaults to
                source-format-derived behavior (jpg/jpeg→JPEG, webp→WEBP, png→PNG via imagequant).

        Returns:
            Compressed image bytes if output_path is None, otherwise None

        Raises:
            ValueError: If quality not in [0, 1] or unsupported format
            FileNotFoundError: If input file does not exist
        """
        if quality < 0 or quality > 1:
            raise ValueError("quality must be between 0 and 1")

        if output_format is not None and output_format.lower() not in {
            "jpeg",
            "png",
            "webp",
        }:
            raise ValueError(f"Unsupported output_format: {output_format}")

        if isinstance(input_path, bytes):
            input_path = io.BytesIO(input_path)

        # Guard every entry point, independent of process-global state:
        # the BytesIO/PNG path decodes via img.save() below before any
        # sub-method assigns the cap, so set it up front.
        Image.MAX_IMAGE_PIXELS = MAX_DECODE_PIXELS

        # Handle input
        if isinstance(input_path, (str, Path)):
            input_path = Path(input_path)
            if not input_path.exists():
                raise FileNotFoundError(f"File does not exist: {input_path}")

            # Check format
            suffix = input_path.suffix.lower()
            if suffix not in self.SUPPORTED_FORMATS:
                raise ValueError(f"Unsupported format: {suffix}")

            # Select compression method based on format
            if suffix == ".png" and output_format is None:
                return self._compress_png(
                    input_path, output_path, quality, max_dimension
                )
            else:
                return self._compress_with_pillow(
                    input_path,
                    output_path,
                    quality,
                    suffix,
                    max_dimension,
                    output_format,
                )
        else:
            # File object, need to read to determine format
            img = Image.open(input_path)
            if not img.format:
                raise ValueError("Cannot detect image format")
            format_name = img.format.lower()

            if format_name == "png" and output_format is None:
                # PNG requires temporary file; always clean it up, even on failure.
                import tempfile

                tmp_path: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        suffix=".png", delete=False
                    ) as tmp:
                        tmp_path = Path(tmp.name)
                        img.save(tmp.name, "PNG")
                        return self._compress_png(
                            tmp.name, output_path, quality, max_dimension
                        )
                finally:
                    if tmp_path is not None:
                        tmp_path.unlink(missing_ok=True)
            else:
                # Reset file pointer
                if hasattr(input_path, "seek"):
                    input_path.seek(0)
                return self._compress_with_pillow(
                    input_path,
                    output_path,
                    quality,
                    f".{format_name}",
                    max_dimension,
                    output_format,
                )

    def compress_if_needed(
        self,
        raw_bytes: bytes,
        *,
        max_dimension: int = SEND_COMPRESS_MAX_DIMENSION,
        quality: float = SEND_COMPRESS_QUALITY,
        trigger_bytes: int = SEND_COMPRESS_TRIGGER_BYTES,
        output_format: str | None = None,
    ) -> bytes:
        """Responsive send-time compression: compress only when the image actually exceeds limits.

        Behavior:
        - Animated GIFs/WebP (n_frames > 1): returned unchanged to preserve animation.
        - Images at or under both ``max_dimension`` and ``trigger_bytes``: returned unchanged
          (zero-cost fast path — upload/URL images already compressed upstream).
        - Oversized images: compressed via :meth:`compress`. Falls back to the original bytes
          on any failure so send-time compression can never break a call.

        ``trigger_bytes`` is measured in base64 space (the raw bytes are inflated
        ~4/3 before comparison), mirroring provider per-image ceilings.

        Returns:
            Compressed or original bytes (never None).
        """
        if not raw_bytes:
            return raw_bytes

        try:
            Image.MAX_IMAGE_PIXELS = MAX_DECODE_PIXELS
            with Image.open(io.BytesIO(raw_bytes)) as probe:
                format_name = (probe.format or "").lower()
                # Animated GIF/WebP: preserve animation — do not re-encode to a static frame.
                if format_name in ("gif", "webp"):
                    try:
                        if getattr(probe, "n_frames", 1) > 1:
                            return raw_bytes
                    except (AttributeError, OSError):
                        pass
                width, height = probe.size
        except Exception as exc:
            logger.warning("Image probe failed in compress_if_needed: %s", exc)
            return raw_bytes

        # Compare in base64 space: provider per-image ceilings (Claude 10 MiB
        # direct / 5 MiB Bedrock·Vertex·OpenAI / 4 MiB Groq) are base64 sizes,
        # and raw bytes inflate ~4/3 on embedding. A raw-byte check would let
        # a 4 MiB raw image (≈5.3 MiB base64) sail past a 5 MiB ceiling and
        # burn a recovery round-trip.
        b64_len = 4 * ((len(raw_bytes) + 2) // 3)
        if (
            width <= max_dimension
            and height <= max_dimension
            and b64_len <= trigger_bytes
        ):
            return raw_bytes

        try:
            compressed = self.compress(
                io.BytesIO(raw_bytes),
                output_path=None,
                quality=quality,
                max_dimension=max_dimension,
                output_format=output_format,
            )
        except Exception as exc:
            logger.warning("Image compression failed in compress_if_needed: %s", exc)
            return raw_bytes

        if not compressed or len(compressed) >= len(raw_bytes):
            return raw_bytes
        return compressed

    def _resize_if_needed(
        self, img: Image.Image, max_dimension: int | None
    ) -> Image.Image:
        """Resize image if it exceeds max_dimension."""
        if not max_dimension:
            return img

        width, height = img.size
        if width > max_dimension or height > max_dimension:
            ratio = min(max_dimension / width, max_dimension / height)
            new_size = (int(width * ratio), int(height * ratio))
            return img.resize(new_size, Image.Resampling.LANCZOS)
        return img

    def slice_long_image_if_needed(
        self,
        img_bytes: bytes,
        *,
        max_dimension: int = SEND_COMPRESS_MAX_DIMENSION,
        aspect_ratio_threshold: float = 1.8,
        min_height_threshold: int = 800,
        overlap_pixels: int = 60,
    ) -> list[bytes]:
        """Slice vertically extreme long screenshots into sequential overlapping tiles.

        If the image aspect ratio (height / width) is below threshold or height < min_height_threshold,
        returns the original bytes in a single-element list.
        Otherwise, slices the image into multiple overlapping tiles preserving full horizontal
        resolution so text does not degrade into unrecognizable artifacts.
        """
        Image.MAX_IMAGE_PIXELS = MAX_DECODE_PIXELS
        try:
            with Image.open(io.BytesIO(img_bytes)) as img:
                width, height = img.size
                if width <= 0 or height <= 0:
                    return [img_bytes]

                aspect_ratio = height / width
                if aspect_ratio < aspect_ratio_threshold or height < min_height_threshold:
                    return [img_bytes]

                # Determine tile height (target a square or slightly tall block bounded by max_dimension)
                tile_height = min(max(int(width * 1.5), 400), max_dimension)
                overlap = min(overlap_pixels, tile_height // 4)
                stride = max(100, tile_height - overlap)

                slices: list[bytes] = []
                top = 0
                while top < height:
                    bottom = min(top + tile_height, height)
                    box = (0, top, width, bottom)
                    tile = img.crop(box)

                    buf = io.BytesIO()
                    tile_format = img.format or "PNG"
                    tile.save(buf, format=tile_format, optimize=True)
                    slices.append(buf.getvalue())

                    if bottom >= height:
                        break
                    top += stride

                return slices if slices else [img_bytes]
        except Exception as exc:
            logger.warning("slice_long_image_if_needed failed fallback to original: %s", exc)
            return [img_bytes]


    def _compress_with_pillow(
        self,
        input_source: Path | BinaryIO,
        output_path: str | Path | None,
        quality: float,
        format_suffix: str,
        max_dimension: int | None,
        output_format: str | None = None,
    ) -> bytes | None:
        """Compress image using Pillow (for jpg/jpeg/webp)."""
        # Convert 0-1 quality to Pillow's 1-100
        pillow_quality = int(quality * 100)
        pillow_quality = max(1, min(100, pillow_quality))

        # Open image
        Image.MAX_IMAGE_PIXELS = MAX_DECODE_PIXELS
        img: Image.Image = Image.open(input_source)

        # Apply EXIF orientation
        from PIL import ImageOps

        img = ImageOps.exif_transpose(img)

        # Resize if needed
        img = self._resize_if_needed(img, max_dimension)

        # Convert to RGB if needed for JPEG
        if format_suffix in [".jpg", ".jpeg"] or output_format == "jpeg":
            if img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            ):
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

        # Determine save format
        save_format = _resolve_save_format(format_suffix, output_format)

        # Compress and save
        if output_path:
            img.save(
                output_path, format=save_format, quality=pillow_quality, optimize=True
            )
            return None
        else:
            buffer = io.BytesIO()
            img.save(buffer, format=save_format, quality=pillow_quality, optimize=True)
            return buffer.getvalue()

    def _compress_png(
        self,
        input_path: str | Path,
        output_path: str | Path | None,
        quality: float,
        max_dimension: int | None,
    ) -> bytes | None:
        """Compress PNG using imagequant or Pillow fallback."""
        result = self._compress_png_with_imagequant(
            input_path, output_path, quality, max_dimension
        )
        if result is not False:  # Success or returned bytes
            return result  # type: ignore

        # Pillow fallback
        return self._compress_png_with_pillow(
            input_path, output_path, quality, max_dimension
        )

    def _compress_png_with_imagequant(
        self,
        input_path: str | Path,
        output_path: str | Path | None,
        quality: float,
        max_dimension: int | None,
    ) -> bytes | None | bool:
        """Compress PNG using imagequant."""
        try:
            import imagequant  # type: ignore[import-not-found]
            from PIL import ImageOps

            Image.MAX_IMAGE_PIXELS = MAX_DECODE_PIXELS
            img: Image.Image = Image.open(input_path)
            img = ImageOps.exif_transpose(img)

            # Resize if needed
            img = self._resize_if_needed(img, max_dimension)

            # Check image characteristics for imagequant suitability
            if img.mode == "P" or (img.mode == "L" and quality > 0.5):
                return False  # Use Pillow fallback

            # Preserve alpha channel for high quality
            has_alpha = img.mode == "RGBA"
            if has_alpha and quality > 0.8:
                return False

            # Convert quality to imagequant parameters
            if quality < 0.3:
                max_colors = int(8 + quality * 80)  # 8-32
            elif quality < 0.6:
                max_colors = int(32 + (quality - 0.3) * 320)  # 32-128
            else:
                max_colors = int(128 + (quality - 0.6) * 320)  # 128-256

            max_colors = max(2, min(256, max_colors))

            min_quality = int(quality * 60)  # 0-60
            max_quality = int(60 + quality * 40)  # 60-100

            # Quantize image using imagequant
            quantized_img = imagequant.quantize_pil_image(
                img,
                dithering_level=(
                    0.0 if quality < 0.3 else (0.5 if quality < 0.7 else 1.0)
                ),
                max_colors=max_colors,
                min_quality=min_quality,
                max_quality=max_quality,
            )

            # PNG compression level
            compress_level = 9  # Always use highest compression

            # Compress to memory first to check size
            buffer = io.BytesIO()
            quantized_img.save(
                buffer, "PNG", optimize=True, compress_level=compress_level
            )
            compressed_data = buffer.getvalue()

            # Check compressed size
            if isinstance(input_path, (str, Path)):
                original_size = Path(input_path).stat().st_size
                if (
                    len(compressed_data) >= original_size * 0.9
                ):  # No significant reduction
                    return False  # Use fallback

            if output_path:
                with open(output_path, "wb") as f:
                    f.write(compressed_data)
                return None
            else:
                return compressed_data

        except Exception as e:
            logger.warning(f"imagequant compression failed, using Pillow fallback: {e}")
            return False  # Fallback needed

    def _compress_png_with_pillow(
        self,
        input_path: str | Path,
        output_path: str | Path | None,
        quality: float,
        max_dimension: int | None,
    ) -> bytes | None:
        """Compress PNG using Pillow."""
        from PIL import ImageOps

        Image.MAX_IMAGE_PIXELS = MAX_DECODE_PIXELS
        img: Image.Image = Image.open(input_path)
        img = ImageOps.exif_transpose(img)

        # Resize if needed
        img = self._resize_if_needed(img, max_dimension)

        # Adjust PNG compression based on quality
        if quality < 0.5:
            # Low quality: convert to P mode (palette) to reduce colors
            colors = int(32 + quality * 448)  # 32-256 colors
            img = img.quantize(colors=colors, method=2)  # method=2 is MEDIANCUT

        # PNG compression parameters
        compress_level = int((1 - quality) * 9)  # 0-9, higher = stronger

        if output_path:
            img.save(output_path, "PNG", optimize=True, compress_level=compress_level)
            return None
        else:
            buffer = io.BytesIO()
            img.save(buffer, "PNG", optimize=True, compress_level=compress_level)
            return buffer.getvalue()


# Global instance
image_compressor = ImageCompressor()


def _resolve_save_format(format_suffix: str, output_format: str | None) -> str:
    """Map input/forced format to a Pillow save format.

    - output_format wins when provided ("jpeg"→JPEG, "png"→PNG, "webp"→WEBP).
    - Otherwise derives from the source suffix (jpg/jpeg→JPEG, anything else→WEBP).
    """
    if output_format:
        return output_format.upper()
    return "JPEG" if format_suffix in [".jpg", ".jpeg"] else "WEBP"
