"""Image compression tool for jpg/jpeg/png formats.

[INPUT]

[OUTPUT]
- bytes | None: compressed image bytes if output_path is None

[POS]
Pure image compression utility. Supports jpg/jpeg/png formats.
Uses Pillow for jpg/jpeg/webp, imagequant for PNG (with Pillow fallback).
"""

from __future__ import annotations

import io
import logging
import typing
from pathlib import Path
from typing import BinaryIO

from PIL import Image

logger = logging.getLogger(__name__)


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
    ) -> bytes | None:
        """Compress image.

        Args:
            input_path: Input image path, file object, or raw bytes
            output_path: Output image path, if None returns bytes
            quality: Compression quality (0.0-1.0), 0=lowest, 1=highest
            max_dimension: Maximum dimension (width or height). If exceeded, image is downsampled.

        Returns:
            Compressed image bytes if output_path is None, otherwise None

        Raises:
            ValueError: If quality not in [0, 1] or unsupported format
            FileNotFoundError: If input file does not exist
        """
        if quality < 0 or quality > 1:
            raise ValueError("quality must be between 0 and 1")

        if isinstance(input_path, bytes):
            input_path = io.BytesIO(input_path)

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
            if suffix == ".png":
                return self._compress_png(input_path, output_path, quality, max_dimension)
            else:
                return self._compress_with_pillow(input_path, output_path, quality, suffix, max_dimension)
        else:
            # File object, need to read to determine format
            img = Image.open(input_path)
            if not img.format:
                raise ValueError("Cannot detect image format")
            format_name = img.format.lower()

            if format_name == "png":
                # PNG requires temporary file
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    img.save(tmp.name, "PNG")
                    result = self._compress_png(tmp.name, output_path, quality, max_dimension)
                Path(tmp.name).unlink()
                return result
            else:
                # Reset file pointer
                if hasattr(input_path, "seek"):
                    input_path.seek(0)
                return self._compress_with_pillow(input_path, output_path, quality, f".{format_name}", max_dimension)

    def _resize_if_needed(self, img: Image.Image, max_dimension: int | None) -> Image.Image:
        """Resize image if it exceeds max_dimension."""
        if not max_dimension:
            return img

        width, height = img.size
        if width > max_dimension or height > max_dimension:
            ratio = min(max_dimension / width, max_dimension / height)
            new_size = (int(width * ratio), int(height * ratio))
            return img.resize(new_size, Image.Resampling.LANCZOS)
        return img

    def _compress_with_pillow(
        self,
        input_source: Path | BinaryIO,
        output_path: str | Path | None,
        quality: float,
        format_suffix: str,
        max_dimension: int | None,
    ) -> bytes | None:
        """Compress image using Pillow (for jpg/jpeg/webp)."""
        # Convert 0-1 quality to Pillow's 1-100
        pillow_quality = int(quality * 100)
        pillow_quality = max(1, min(100, pillow_quality))

        # Open image
        Image.MAX_IMAGE_PIXELS = None
        img = Image.open(input_source)

        # Apply EXIF orientation
        from PIL import ImageOps

        img = ImageOps.exif_transpose(img)

        # Resize if needed
        img = self._resize_if_needed(img, max_dimension)

        # Convert to RGB if needed for JPEG
        if format_suffix in [".jpg", ".jpeg"]:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

        # Determine save format
        save_format = "JPEG" if format_suffix in [".jpg", ".jpeg"] else "WEBP"

        # Compress and save
        if output_path:
            img.save(output_path, format=save_format, quality=pillow_quality, optimize=True)
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
        result = self._compress_png_with_imagequant(input_path, output_path, quality, max_dimension)
        if result is not False:  # Success or returned bytes
            return result  # type: ignore

        # Pillow fallback
        return self._compress_png_with_pillow(input_path, output_path, quality, max_dimension)

    def _compress_png_with_imagequant(
        self,
        input_path: str | Path,
        output_path: str | Path | None,
        quality: float,
        max_dimension: int | None,
    ) -> bytes | None | bool:
        """Compress PNG using imagequant."""
        try:
            import imagequant
            from PIL import ImageOps

            Image.MAX_IMAGE_PIXELS = None
            img = Image.open(input_path)
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
                dithering_level=(0.0 if quality < 0.3 else (0.5 if quality < 0.7 else 1.0)),
                max_colors=max_colors,
                min_quality=min_quality,
                max_quality=max_quality,
            )

            # PNG compression level
            compress_level = 9  # Always use highest compression

            # Compress to memory first to check size
            buffer = io.BytesIO()
            quantized_img.save(buffer, "PNG", optimize=True, compress_level=compress_level)
            compressed_data = buffer.getvalue()

            # Check compressed size
            if isinstance(input_path, (str, Path)):
                original_size = Path(input_path).stat().st_size
                if len(compressed_data) >= original_size * 0.9:  # No significant reduction
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

        Image.MAX_IMAGE_PIXELS = None
        img = Image.open(input_path)
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
