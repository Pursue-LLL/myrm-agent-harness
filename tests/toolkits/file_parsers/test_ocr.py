"""Tests for the OCRParser (RapidOCR on ONNX Runtime)."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from myrm_agent_harness.toolkits.file_parsers.ocr import OCRParser, OCRResult


class _FakeOutput:
    """Stand-in for RapidOCR's ``RapidOCROutput`` (parallel tuples)."""

    def __init__(self, txts=(), scores=(), boxes=None) -> None:
        self.txts = txts
        self.scores = scores
        self.boxes = boxes


@contextmanager
def _rapidocr():
    """Install a fake ``rapidocr`` module; yields the mocked ``RapidOCR`` class."""
    fake_module = MagicMock()
    with patch.dict("sys.modules", {"rapidocr": fake_module}):
        yield fake_module.RapidOCR


@contextmanager
def _rapidocr_missing():
    """Simulate the dependency being absent so ``from rapidocr import RapidOCR`` fails."""
    with patch.dict("sys.modules", {"rapidocr": None}):
        yield


class TestGetEngine:
    """Lazy engine initialization and language/GPU wiring."""

    def test_missing_dependency_raises_install_hint(self):
        with _rapidocr_missing(), pytest.raises(ImportError, match="rapidocr is required"):
            OCRParser()._get_engine()

    def test_language_and_gpu_reach_the_engine_params(self):
        with _rapidocr() as engine_cls:
            OCRParser(lang="japan", use_gpu=True)._get_engine()

            params = engine_cls.call_args.kwargs["params"]
            assert params["Rec.lang_type"] == "japan"
            # CJK recognizers need the CJK detector, or page layout degrades.
            assert params["Det.lang_type"] == "ch"
            assert params["EngineConfig.onnxruntime.use_cuda"] is True

    def test_latin_language_pairs_with_the_latin_detector(self):
        with _rapidocr() as engine_cls:
            OCRParser(lang="en")._get_engine()

            params = engine_cls.call_args.kwargs["params"]
            assert params["Rec.lang_type"] == "en"
            assert params["Det.lang_type"] == "en"

    def test_legacy_language_aliases_are_normalized(self):
        with _rapidocr() as engine_cls:
            OCRParser(lang="chinese")._get_engine()
            assert engine_cls.call_args.kwargs["params"]["Rec.lang_type"] == "ch"

    def test_engine_initialized_once(self):
        with _rapidocr() as engine_cls:
            parser = OCRParser()
            assert parser._get_engine() is parser._get_engine()
            assert engine_cls.call_count == 1


class TestParseSync:
    """Inference call and failure handling."""

    def test_result_is_processed(self):
        with _rapidocr():
            parser = OCRParser()
            engine = parser._get_engine()
            engine.return_value = _FakeOutput(txts=("hello",), scores=(0.9,), boxes=None)

            result = parser._parse_sync("/tmp/img.png")

            engine.assert_called_once_with("/tmp/img.png")
            assert result.text == "hello"
            assert result.engine == "rapidocr"

    def test_engine_failure_returns_empty_result(self):
        with _rapidocr():
            parser = OCRParser()
            engine = parser._get_engine()
            engine.side_effect = RuntimeError("inference crashed")

            result = parser._parse_sync("/tmp/img.png")

            assert result.text == ""
            assert result.lines == []


class TestProcessResult:
    """RapidOCR parallel-tuple output parsing."""

    def test_lines_and_average_confidence(self):
        parser = OCRParser(confidence_threshold=0.5)
        result = parser._process_result(_FakeOutput(txts=("hello", "world"), scores=(0.9, 0.6)))

        assert result.text == "hello\nworld"
        assert len(result.lines) == 2
        assert result.lines[0].confidence == 0.9
        assert result.avg_confidence == pytest.approx(0.75)

    def test_low_confidence_lines_are_dropped(self):
        parser = OCRParser(confidence_threshold=0.8)
        result = parser._process_result(_FakeOutput(txts=("keep", "drop"), scores=(0.95, 0.3)))

        assert result.text == "keep"
        assert len(result.lines) == 1

    def test_blank_lines_are_dropped(self):
        parser = OCRParser()
        result = parser._process_result(_FakeOutput(txts=("", "  ", "real"), scores=(0.9, 0.8, 0.7)))

        assert result.text == "real"
        assert len(result.lines) == 1

    def test_no_detections_is_an_empty_result_not_an_error(self):
        parser = OCRParser()
        assert parser._process_result(_FakeOutput()).text == ""
        assert parser._process_result(None).text == ""

    def test_missing_scores_default_to_zero_and_are_filtered_out(self):
        parser = OCRParser(confidence_threshold=0.5)
        result = parser._process_result(_FakeOutput(txts=("no score",), scores=()))

        assert result.text == ""

    def test_numpy_boxes_are_exposed_as_plain_lists(self):
        parser = OCRParser()
        box = np.array([[0, 0], [10, 0], [10, 10], [0, 10]])
        result = parser._process_result(_FakeOutput(txts=("boxed",), scores=(0.9,), boxes=(box,)))

        assert result.lines[0].bbox == [[0, 0], [10, 0], [10, 10], [0, 10]]
        assert isinstance(result.lines[0].bbox, list)

    def test_missing_box_keeps_bbox_none(self):
        parser = OCRParser()
        result = parser._process_result(_FakeOutput(txts=("no box",), scores=(0.9,), boxes=None))

        assert result.text == "no box"
        assert result.lines[0].bbox is None


class TestParseEntryPoints:
    """Public parse entry points."""

    @pytest.mark.asyncio
    async def test_parse_bytes_empty_returns_empty(self):
        assert await OCRParser().parse_bytes(b"") == ""

    @pytest.mark.asyncio
    async def test_parse_bytes_writes_a_temp_file_and_cleans_up(self):
        with _rapidocr():
            parser = OCRParser()
            engine = parser._get_engine()
            engine.return_value = _FakeOutput(txts=("scanned page",), scores=(0.9,))

            text = await parser.parse_bytes(b"fake-png-bytes", suffix=".png")

            assert text == "scanned page"
            call_path = engine.call_args[0][0]
            assert call_path.endswith(".png")
            assert Path(call_path).exists() is False

    @pytest.mark.asyncio
    async def test_parse_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            await OCRParser().parse("/nonexistent/img.png")

    @pytest.mark.asyncio
    async def test_parse_with_details_returns_ocr_result(self, tmp_path):
        img = tmp_path / "img.png"
        img.write_bytes(b"fake-png-bytes")
        with _rapidocr():
            parser = OCRParser()
            engine = parser._get_engine()
            engine.return_value = _FakeOutput(txts=("detail",), scores=(0.9,))

            result = await parser.parse_with_details(str(img))

            assert isinstance(result, OCRResult)
            assert result.text == "detail"
            assert result.engine == "rapidocr"

    @pytest.mark.asyncio
    async def test_parse_with_details_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            await OCRParser().parse_with_details("/nonexistent/img.png")

    def test_supported_extensions(self):
        parser = OCRParser()
        assert ".png" in parser.supported_extensions
        assert ".jpg" in parser.supported_extensions
        assert ".webp" in parser.supported_extensions
