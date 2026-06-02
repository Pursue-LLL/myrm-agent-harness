"""Unit tests for FastComparator (dHash perceptual hash comparison)."""

import base64
import io
import sys
from unittest.mock import patch

import pytest
from PIL import Image

from myrm_agent_harness.toolkits.browser.diff import FastComparator, FastComparisonResult


def create_test_image(width: int = 100, height: int = 100, color: tuple[int, int, int] = (255, 0, 0)) -> str:
    """Create a solid color test image and return as base64."""
    img = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def create_gradient_image(width: int = 100, height: int = 100) -> str:
    """Create a gradient test image and return as base64."""
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (int(x / width * 255), int(y / height * 255), 128)  # type: ignore[index]
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class TestFastComparatorImportHandling:
    """Test suite for import-time exception handling."""

    def test_import_without_pillow(self) -> None:
        """Test module import gracefully handles missing Pillow."""
        original_modules = sys.modules.copy()

        try:
            if "PIL" in sys.modules:
                del sys.modules["PIL"]
            if "PIL.Image" in sys.modules:
                del sys.modules["PIL.Image"]
            if "myrm_agent_harness.toolkits.browser.diff.fast_comparator" in sys.modules:
                del sys.modules["myrm_agent_harness.toolkits.browser.diff.fast_comparator"]

            with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
                import myrm_agent_harness.toolkits.browser.diff.fast_comparator as fc_module

                assert fc_module.Image is None

        finally:
            for key in list(sys.modules.keys()):
                if key not in original_modules:
                    del sys.modules[key]
            sys.modules.update(original_modules)


class TestFastComparator:
    """Test suite for FastComparator."""

    def test_initialization_default_threshold(self) -> None:
        """Test initialization with default similarity_threshold."""
        comparator = FastComparator()
        assert comparator.similarity_threshold == 0.9

    def test_initialization_custom_threshold(self) -> None:
        """Test initialization with custom similarity_threshold."""
        comparator = FastComparator(similarity_threshold=0.8)
        assert comparator.similarity_threshold == 0.8

    def test_initialization_boundary_threshold_zero(self) -> None:
        """Test initialization with threshold = 0.0 (boundary)."""
        comparator = FastComparator(similarity_threshold=0.0)
        assert comparator.similarity_threshold == 0.0

    def test_initialization_boundary_threshold_one(self) -> None:
        """Test initialization with threshold = 1.0 (boundary)."""
        comparator = FastComparator(similarity_threshold=1.0)
        assert comparator.similarity_threshold == 1.0

    def test_initialization_invalid_threshold_too_low(self) -> None:
        """Test initialization fails with threshold < 0."""
        with pytest.raises(ValueError, match="similarity_threshold must be in"):
            FastComparator(similarity_threshold=-0.1)

    def test_initialization_invalid_threshold_too_high(self) -> None:
        """Test initialization fails with threshold > 1."""
        with pytest.raises(ValueError, match="similarity_threshold must be in"):
            FastComparator(similarity_threshold=1.1)

    def test_compare_identical_images(self) -> None:
        """Test comparison of two identical images."""
        comparator = FastComparator()
        img_b64 = create_test_image(color=(100, 150, 200))

        result = comparator.compare(img_b64, img_b64)

        assert isinstance(result, FastComparisonResult)
        assert result.similarity == 1.0
        assert result.hamming_distance == 0
        assert result.is_significant_change is False
        assert result.algorithm == "dhash"

    def test_compare_completely_different_images(self) -> None:
        """Test comparison of completely different images."""
        comparator = FastComparator()
        img1 = create_gradient_image()
        img2_img = Image.new("RGB", (100, 100))
        pixels = img2_img.load()
        for y in range(100):
            for x in range(100):
                pixels[x, y] = (255 - int(x / 100 * 255), 255 - int(y / 100 * 255), 128)  # type: ignore[index]
        buffer = io.BytesIO()
        img2_img.save(buffer, format="PNG")
        img2 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        result = comparator.compare(img1, img2)

        assert result.similarity < 0.95
        assert result.hamming_distance > 0
        assert result.is_significant_change is True

    def test_compare_similar_images(self) -> None:
        """Test comparison of similar images (high similarity)."""
        comparator = FastComparator(similarity_threshold=0.9)
        img1 = create_test_image(color=(100, 100, 100))
        img2 = create_test_image(color=(101, 101, 101))

        result = comparator.compare(img1, img2)

        assert result.similarity >= 0.9
        assert result.is_significant_change is False

    def test_compare_threshold_boundary(self) -> None:
        """Test is_significant_change threshold boundary detection."""
        comparator = FastComparator(similarity_threshold=0.95)
        img1 = create_gradient_image()
        img2 = create_gradient_image()

        result = comparator.compare(img1, img2)

        assert result.similarity == 1.0
        assert result.is_significant_change is False

    def test_compare_different_sizes(self) -> None:
        """Test comparison of images with different sizes."""
        comparator = FastComparator()
        img1 = create_test_image(width=100, height=100, color=(255, 0, 0))
        img2 = create_test_image(width=200, height=200, color=(255, 0, 0))

        result = comparator.compare(img1, img2)

        assert isinstance(result, FastComparisonResult)
        assert result.similarity >= 0.95

    def test_hamming_distance_zero(self) -> None:
        """Test Hamming distance of identical hashes."""
        distance = FastComparator._hamming_distance(0b1010, 0b1010)
        assert distance == 0

    def test_hamming_distance_one_bit(self) -> None:
        """Test Hamming distance with one different bit."""
        distance = FastComparator._hamming_distance(0b1010, 0b1011)
        assert distance == 1

    def test_hamming_distance_multiple_bits(self) -> None:
        """Test Hamming distance with multiple different bits."""
        distance = FastComparator._hamming_distance(0b1010, 0b0101)
        assert distance == 4

    def test_hamming_distance_all_bits_different(self) -> None:
        """Test Hamming distance with all bits different (64-bit)."""
        hash1 = 0xFFFFFFFFFFFFFFFF
        hash2 = 0x0000000000000000
        distance = FastComparator._hamming_distance(hash1, hash2)
        assert distance == 64

    def test_compute_hash_deterministic(self) -> None:
        """Test that hash computation returns the same hash for the same image."""
        comparator = FastComparator()
        img_b64 = create_test_image(color=(128, 128, 128))
        img_bytes = base64.b64decode(img_b64)

        hash1 = comparator._compute_hash_from_bytes(img_bytes)
        hash2 = comparator._compute_hash_from_bytes(img_bytes)

        assert hash1 == hash2

    def test_compute_hash_different_images(self) -> None:
        """Test that hash computation returns different hashes for structurally different images."""
        comparator = FastComparator()

        img1_obj = Image.new("RGB", (100, 100))
        pixels1 = img1_obj.load()
        for y in range(100):
            for x in range(100):
                pixels1[x, y] = (255, 0, 0) if x < 50 else (0, 255, 0)  # type: ignore[index]
        buffer1 = io.BytesIO()
        img1_obj.save(buffer1, format="PNG")
        img1_bytes = buffer1.getvalue()

        img2_obj = Image.new("RGB", (100, 100))
        pixels2 = img2_obj.load()
        for y in range(100):
            for x in range(100):
                pixels2[x, y] = (0, 0, 255) if y < 50 else (255, 255, 0)  # type: ignore[index]
        buffer2 = io.BytesIO()
        img2_obj.save(buffer2, format="PNG")
        img2_bytes = buffer2.getvalue()

        hash1 = comparator._compute_hash_from_bytes(img1_bytes)
        hash2 = comparator._compute_hash_from_bytes(img2_bytes)

        assert hash1 != hash2

    def test_from_bytes(self) -> None:
        """Test from_bytes static method."""
        img = Image.new("RGB", (100, 100), (200, 100, 50))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        hash_value = FastComparator.from_bytes(image_bytes)

        assert isinstance(hash_value, int)
        assert hash_value >= 0

    def test_from_bytes_deterministic(self) -> None:
        """Test from_bytes returns same hash for same image bytes."""
        img = Image.new("RGB", (100, 100), (50, 100, 150))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        hash1 = FastComparator.from_bytes(image_bytes)
        hash2 = FastComparator.from_bytes(image_bytes)

        assert hash1 == hash2
        assert isinstance(hash1, int)

    def test_from_bytes_with_gradient_image(self) -> None:
        """Test from_bytes correctly computes hash for gradient image."""
        img = Image.new("RGB", (100, 100))
        pixels = img.load()
        for y in range(100):
            for x in range(100):
                brightness = int((x / 100) * 255)
                pixels[x, y] = (brightness, brightness, brightness)  # type: ignore[index]

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        hash_value = FastComparator.from_bytes(image_bytes)

        assert isinstance(hash_value, int)
        assert hash_value > 0

    def test_result_to_llm_message_similar(self) -> None:
        """Test to_llm_message for similar images."""
        comparator = FastComparator()
        img = create_test_image()
        result = comparator.compare(img, img)

        message = result.to_llm_message()

        assert "SIMILAR" in message
        assert "Similarity:" in message
        assert "hamming distance: 0/64" in message
        assert "dHash" in message

    def test_result_to_llm_message_significant_change(self) -> None:
        """Test to_llm_message for significantly different images."""
        comparator = FastComparator(similarity_threshold=0.95)
        img1 = create_gradient_image()

        img2_obj = Image.new("RGB", (100, 100))
        pixels = img2_obj.load()
        for y in range(100):
            for x in range(100):
                pixels[x, y] = (0, 0, 255) if (x + y) % 2 == 0 else (255, 255, 0)  # type: ignore[index]
        buffer = io.BytesIO()
        img2_obj.save(buffer, format="PNG")
        img2 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        result = comparator.compare(img1, img2)
        message = result.to_llm_message()

        assert "CHANGE" in message
        assert "Similarity:" in message
        assert "hamming distance:" in message
        assert "dHash" in message

    def test_result_immutability(self) -> None:
        """Test that FastComparisonResult is immutable (frozen dataclass)."""
        comparator = FastComparator()
        img = create_test_image()
        result = comparator.compare(img, img)

        with pytest.raises(Exception):
            result.similarity = 0.5  # type: ignore[misc]

    def test_result_protocol_compliance(self) -> None:
        """Test that FastComparisonResult implements ComparisonResult protocol."""
        comparator = FastComparator()
        img = create_test_image()
        result = comparator.compare(img, img)

        assert hasattr(result, "similarity")
        assert hasattr(result, "is_significant_change")
        assert hasattr(result, "algorithm")
        assert hasattr(result, "to_llm_message")
        assert callable(result.to_llm_message)

    def test_initialization_without_pillow(self) -> None:
        """Test initialization fails when Pillow is not installed."""
        with patch("myrm_agent_harness.toolkits.browser.diff.fast_comparator.Image", None):
            with pytest.raises(ImportError, match="Pillow is required for FastComparator"):
                FastComparator()

    def test_from_bytes_without_pillow(self) -> None:
        """Test from_bytes fails when Pillow is not installed."""
        img = Image.new("RGB", (100, 100), (50, 100, 150))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        with patch("myrm_agent_harness.toolkits.browser.diff.fast_comparator.Image", None):
            with pytest.raises(ImportError, match="Pillow is required for FastComparator"):
                FastComparator.from_bytes(image_bytes)

    def test_input_validation_too_large(self) -> None:
        """Test that compare rejects oversized base64 input."""
        comparator = FastComparator()
        large_b64 = "A" * (11 * 1024 * 1024)
        img = create_test_image()

        with pytest.raises(ValueError, match="too large"):
            comparator.compare(large_b64, img)

    def test_input_validation_invalid_base64(self) -> None:
        """Test that compare rejects invalid base64."""
        comparator = FastComparator()
        invalid_b64 = "not-valid-base64!!!"
        img = create_test_image()

        with pytest.raises(ValueError, match="not valid base64"):
            comparator.compare(invalid_b64, img)

    def test_input_validation_invalid_image(self) -> None:
        """Test that compare rejects non-image data."""
        comparator = FastComparator()
        text_b64 = base64.b64encode(b"just some text").decode("utf-8")
        img = create_test_image()

        with pytest.raises(ValueError, match="not a valid image"):
            comparator.compare(text_b64, img)

    def test_input_validation_oversized_dimensions(self) -> None:
        """Test that compare rejects images with dimensions exceeding limit."""
        comparator = FastComparator()
        huge_img = Image.new("RGB", (5000, 5000), (255, 0, 0))
        buffer = io.BytesIO()
        huge_img.save(buffer, format="PNG")
        huge_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        img = create_test_image()

        with pytest.raises(ValueError, match="dimensions too large"):
            comparator.compare(huge_b64, img)
