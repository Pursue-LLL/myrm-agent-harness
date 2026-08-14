"""Tests for the OCRParser (PaddleOCR 2.x/3.x compatible)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.file_parsers.ocr import OCRParser, OCRResult


def _fake_paddleocr(version: str, raise_import: bool = False) -> MagicMock:
    """Build a fake paddleocr module with a given version."""
    fake = MagicMock()
    if raise_import:
        fake.PaddleOCR = MagicMock(side_effect=ImportError("paddleocr is required"))
        return fake
    fake.__version__ = version
    fake.PaddleOCR = MagicMock()
    return fake


def _patch_paddleocr(version: str, raise_import: bool = False):
    return patch.dict(
        "sys.modules",
        {"paddleocr": _fake_paddleocr(version, raise_import)},
    )


def _paddleocr_mod() -> MagicMock:
    return sys.modules["paddleocr"]


class TestGetEngine:
    """Lazy engine initialization and version-dependent construction."""

    def test_import_error_raises_hint(self):
        with _patch_paddleocr("3.2.0", raise_import=True), pytest.raises(ImportError, match="paddleocr is required"):
            OCRParser()._get_engine()

    def test_v2_uses_legacy_constructor_args(self):
        with _patch_paddleocr("2.7.3"):
            parser = OCRParser(lang="en", use_gpu=True)
            engine = parser._get_engine()

            fake_mod = _paddleocr_mod()
            assert engine is fake_mod.PaddleOCR.return_value
            _, kwargs = fake_mod.PaddleOCR.call_args
            assert kwargs["use_angle_cls"] is True
            assert kwargs["use_gpu"] is True
            assert kwargs["lang"] == "en"
            assert kwargs["show_log"] is False

    def test_v3_uses_paddlex_constructor_args(self):
        with _patch_paddleocr("3.2.0"):
            parser = OCRParser(lang="ch", use_gpu=False)
            engine = parser._get_engine()

            fake_mod = _paddleocr_mod()
            assert engine is fake_mod.PaddleOCR.return_value
            _, kwargs = fake_mod.PaddleOCR.call_args
            assert kwargs["use_textline_orientation"] is True
            assert kwargs["device"] == "cpu"
            assert kwargs["lang"] == "ch"
            assert "use_angle_cls" not in kwargs

    def test_engine_cached_after_first_initialization(self):
        with _patch_paddleocr("3.2.0"):
            parser = OCRParser()
            first = parser._get_engine()
            second = parser._get_engine()

            fake_mod = _paddleocr_mod()
            assert first is second
            assert fake_mod.PaddleOCR.call_count == 1


class TestParseSync:
    """Inference call compatibility across engine generations."""

    def test_v2_calls_ocr_with_cls(self):
        with _patch_paddleocr("2.7.3"):
            parser = OCRParser()
            engine = parser._get_engine()
            engine.ocr.return_value = [[[[0, 0, 10, 10], ("hello", 0.9)]]]

            result = parser._parse_sync("/tmp/img.png")

        engine.ocr.assert_called_once_with("/tmp/img.png", cls=True)
        assert result.text == "hello"

    def test_v3_calls_predict(self):
        with _patch_paddleocr("3.2.0"):
            parser = OCRParser()
            engine = parser._get_engine()
            engine.predict.return_value = [{"rec_texts": ["hello", "world"], "rec_scores": [0.9, 0.8], "dt_polys": []}]

            result = parser._parse_sync("/tmp/img.png")

        engine.predict.assert_called_once_with("/tmp/img.png")
        assert result.text == "hello\nworld"

    def test_engine_failure_returns_empty_result(self):
        with _patch_paddleocr("3.2.0"):
            parser = OCRParser()
            engine = parser._get_engine()
            engine.predict.side_effect = RuntimeError("gpu out of memory")

            result = parser._parse_sync("/tmp/img.png")

        assert result.text == ""
        assert result.lines == []


class TestProcessRawResultV2:
    """2.x nested-list output parsing."""

    def test_basic_lines_with_confidence(self):
        parser = OCRParser(confidence_threshold=0.5)
        raw = [
            [
                [[0, 0, 10, 10], ("hello", 0.9)],
                [[10, 10, 20, 20], ("world", 0.6)],
            ]
        ]
        result = parser._process_raw_result(raw)

        assert result.text == "hello\nworld"
        assert len(result.lines) == 2
        assert result.lines[0].confidence == 0.9
        assert result.lines[0].bbox == [0, 0, 10, 10]
        assert result.avg_confidence == pytest.approx(0.75)

    def test_low_confidence_lines_filtered(self):
        parser = OCRParser(confidence_threshold=0.8)
        raw = [[[[0, 0, 10, 10], ("keep", 0.95)], [[10, 10, 20, 20], ("drop", 0.3)]]]
        result = parser._process_raw_result(raw)

        assert result.text == "keep"
        assert len(result.lines) == 1

    def test_blank_or_malformed_items_skipped(self):
        parser = OCRParser()
        raw = [[None, [0, 0, 10, 10], [[0, 0, 10, 10], "no-conf"], [[0, 0, 10, 10], ("ok", 0.9)]]]
        result = parser._process_raw_result(raw)

        assert result.text == "ok"

    def test_empty_result_returns_empty(self):
        parser = OCRParser()
        assert parser._process_raw_result(None).text == ""
        assert parser._process_raw_result([]).text == ""
        assert parser._process_raw_result([None]).text == ""


class TestProcessRawResultV3:
    """3.x PaddleX dict-like output parsing."""

    def test_paddlex_result_parsed(self):
        parser = OCRParser(confidence_threshold=0.5)
        raw = [
            {
                "rec_texts": ["line one", "line two"],
                "rec_scores": [0.91, 0.72],
                "dt_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]], [[20, 0], [30, 0], [30, 10], [20, 10]]],
            }
        ]
        result = parser._process_raw_result(raw)

        assert result.text == "line one\nline two"
        assert len(result.lines) == 2
        assert result.lines[0].bbox == [[0, 0], [10, 0], [10, 10], [0, 10]]
        assert result.avg_confidence == pytest.approx(0.815)

    def test_paddlex_missing_scores_defaults_zero(self):
        parser = OCRParser(confidence_threshold=0.0)
        raw = [{"rec_texts": ["no scores"], "rec_scores": [], "dt_polys": []}]
        result = parser._process_raw_result(raw)

        assert result.text == "no scores"
        assert result.lines[0].confidence == 0.0

    def test_paddlex_blank_texts_filtered(self):
        parser = OCRParser()
        raw = [{"rec_texts": ["", "  ", "real"], "rec_scores": [0.9, 0.8, 0.7], "dt_polys": []}]
        result = parser._process_raw_result(raw)

        assert result.text == "real"
        assert len(result.lines) == 1

    def test_paddlex_numpy_polys_converted_to_list(self):
        """PaddleX dt_polys entries (numpy arrays) are exposed as plain lists (2.x parity)."""
        import numpy as np

        parser = OCRParser()
        raw = [
            {
                "rec_texts": ["boxed"],
                "rec_scores": [0.9],
                "dt_polys": [np.array([[0, 0], [10, 0], [10, 10], [0, 10]])],
            }
        ]
        result = parser._process_raw_result(raw)

        assert result.lines[0].bbox == [[0, 0], [10, 0], [10, 10], [0, 10]]
        assert isinstance(result.lines[0].bbox, list)

    def test_paddlex_missing_poly_keeps_bbox_none(self):
        """When dt_polys is shorter than rec_texts, bbox falls back to None."""
        parser = OCRParser()
        raw = [{"rec_texts": ["no poly"], "rec_scores": [0.9], "dt_polys": []}]
        result = parser._process_raw_result(raw)

        assert result.text == "no poly"
        assert result.lines[0].bbox is None


class TestParseBytesAndParse:
    """Public parse entry points."""

    @pytest.mark.asyncio
    async def test_parse_bytes_empty_returns_empty(self):
        parser = OCRParser()
        assert await parser.parse_bytes(b"") == ""

    @pytest.mark.asyncio
    async def test_parse_bytes_writes_temp_and_parses(self):
        with _patch_paddleocr("3.2.0"):
            parser = OCRParser()
            engine = parser._get_engine()
            engine.predict.return_value = [{"rec_texts": ["scanned page"], "rec_scores": [0.9], "dt_polys": []}]

            text = await parser.parse_bytes(b"fake-png-bytes", suffix=".png")

        assert text == "scanned page"
        # temp file was created and passed to engine
        call_path = engine.predict.call_args[0][0]
        assert Path(call_path).exists() is False  # deleted after parse
        assert call_path.endswith(".png")

    @pytest.mark.asyncio
    async def test_parse_missing_file_raises(self):
        parser = OCRParser()
        with pytest.raises(FileNotFoundError):
            await parser.parse("/nonexistent/img.png")

    @pytest.mark.asyncio
    async def test_parse_with_details_returns_ocr_result(self, tmp_path):
        img = tmp_path / "img.png"
        img.write_bytes(b"fake-png-bytes")
        with _patch_paddleocr("2.7.3"):
            parser = OCRParser()
            engine = parser._get_engine()
            engine.ocr.return_value = [[[[0, 0, 10, 10], ("detail", 0.9)]]]

            result = await parser.parse_with_details(str(img))

        assert isinstance(result, OCRResult)
        assert result.text == "detail"
        assert result.engine == "paddleocr"

    @pytest.mark.asyncio
    async def test_parse_with_details_missing_file_raises(self):
        parser = OCRParser()
        with pytest.raises(FileNotFoundError):
            await parser.parse_with_details("/nonexistent/img.png")

    @pytest.mark.asyncio
    async def test_paddlex_low_confidence_lines_filtered(self):
        parser = OCRParser(confidence_threshold=0.8)
        raw = [{"rec_texts": ["keep", "drop"], "rec_scores": [0.95, 0.3], "dt_polys": []}]
        result = parser._process_raw_result(raw)

        assert result.text == "keep"
        assert len(result.lines) == 1

    def test_supported_extensions(self):
        parser = OCRParser()
        assert ".png" in parser.supported_extensions
        assert ".jpg" in parser.supported_extensions
        assert ".webp" in parser.supported_extensions
