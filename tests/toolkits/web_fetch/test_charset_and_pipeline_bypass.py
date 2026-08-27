"""Comprehensive Unit tests for CharsetDetector and Pipeline structured data bypass."""

import json

import pytest

from myrm_agent_harness.toolkits.web_fetch.charset_detector import (
    _normalize_encoding_name,
    detect_and_decode_html,
    probe_meta_charset,
)
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType, FetchResult
from myrm_agent_harness.toolkits.web_fetch.pipeline import ContentPipeline


def test_normalize_encoding_name():
    assert _normalize_encoding_name(None) is None
    assert _normalize_encoding_name("") is None
    assert _normalize_encoding_name("GB2312") == "gb18030"
    assert _normalize_encoding_name("GBK") == "gb18030"
    assert _normalize_encoding_name("utf-8") == "utf-8"
    assert _normalize_encoding_name("Big5") == "big5"
    assert _normalize_encoding_name("Shift_JIS") == "shift_jis"
    assert _normalize_encoding_name("euc-jp") == "euc_jp"
    assert _normalize_encoding_name("euc-kr") == "euc_kr"
    assert _normalize_encoding_name("latin1") == "iso-8859-1"
    assert _normalize_encoding_name("custom-enc") == "custom-enc"


def test_empty_bytes_charset():
    text, enc = detect_and_decode_html(b"")
    assert text == ""
    assert enc == "utf-8"
    assert probe_meta_charset(b"") is None


def test_meta_charset_detection_gb2312():
    html_gbk = '<html><head><meta charset="gb2312"><title>测试标题</title></head><body>通知内容</body></html>'.encode(
        "gb18030"
    )
    detected = probe_meta_charset(html_gbk)
    assert detected == "gb18030"
    text, enc = detect_and_decode_html(html_gbk)
    assert enc == "gb18030"
    assert "测试标题" in text
    assert "通知内容" in text


def test_meta_http_equiv_charset_detection_gbk():
    html_gbk = (
        '<html><head><meta http-equiv="Content-Type" content="text/html; charset=gbk">'
        "<title>政府申报通知</title></head><body>截止日期2026年</body></html>"
    ).encode("gb18030")
    detected = probe_meta_charset(html_gbk)
    assert detected == "gb18030"
    text, enc = detect_and_decode_html(html_gbk)
    assert enc == "gb18030"
    assert "政府申报通知" in text


def test_meta_invalid_encoding_fallback():
    html_invalid_meta = b'<html><head><meta charset="invalid_fake_encoding_xyz"><title>Fallback</title></head><body>Hello</body></html>'
    detected = probe_meta_charset(html_invalid_meta)
    assert detected == "invalid-fake-encoding-xyz"
    text, enc = detect_and_decode_html(html_invalid_meta)
    assert enc == "utf-8"
    assert "Fallback" in text


def test_header_invalid_encoding_fallback():
    html_valid = "<html><head><title>Fallback</title></head><body>Hello</body></html>".encode("utf-8")
    text, enc = detect_and_decode_html(html_valid, header_encoding="invalid_fake_xyz")
    assert enc == "utf-8"
    assert "Fallback" in text


def test_shift_jis_detection():
    html_sjis = '<html><head><meta charset="Shift_JIS"><title>テスト</title></head><body>お知らせ</body></html>'.encode(
        "shift_jis"
    )
    text, enc = detect_and_decode_html(html_sjis)
    assert enc == "shift_jis"
    assert "テスト" in text


def test_euc_kr_detection():
    html_euckr = '<html><head><meta charset="euc-kr"><title>한국어</title></head><body>환영합니다</body></html>'.encode(
        "euc_kr"
    )
    text, enc = detect_and_decode_html(html_euckr)
    assert enc == "euc_kr"
    assert "한국어" in text


def test_big5_detection():
    html_big5 = '<html><head><meta charset="big5"><title>繁體中文</title></head><body>歡迎光臨</body></html>'.encode(
        "big5"
    )
    text, enc = detect_and_decode_html(html_big5)
    assert enc == "big5"
    assert "繁體中文" in text


def test_utf8_fallback_clean():
    html_utf8 = "<html><head><title>Modern Page</title></head><body>Hello world!</body></html>".encode("utf-8")
    text, enc = detect_and_decode_html(html_utf8)
    assert enc == "utf-8"
    assert "Modern Page" in text


def test_header_encoding_explicit():
    html_gbk = "<html><head><title>GBK Header</title></head><body>中文内容</body></html>".encode("gb18030")
    text, enc = detect_and_decode_html(html_gbk, header_encoding="gbk")
    assert enc == "gb18030"
    assert "中文内容" in text


def test_raw_cjk_fallback_no_meta():
    raw_gbk = "这是一段没有meta标签的纯GBK中文通知段落内容".encode("gb18030")
    text, enc = detect_and_decode_html(raw_gbk)
    assert enc == "gb18030"
    assert "纯GBK中文通知" in text


def test_raw_shift_jis_fallback_no_meta():
    raw_sjis = "これは日本語のテキストです。".encode("shift_jis")
    # Shift-JIS without meta or header will be tried in CJK ladder
    text, enc = detect_and_decode_html(raw_sjis)
    assert text != ""


def test_raw_euc_kr_fallback_no_meta():
    raw_euckr = "안녕하세요 이것은 한국어 텍스트입니다.".encode("euc_kr")
    text, enc = detect_and_decode_html(raw_euckr)
    assert text != ""


def test_raw_big5_fallback_no_meta():
    raw_big5 = "這是一段繁體中文測試內容。".encode("big5")
    text, enc = detect_and_decode_html(raw_big5)
    assert text != ""


def test_binary_unrecognized_fallback():
    # Random un-decodable byte sequence
    un_decodable = bytes([0x80, 0x81, 0xFF, 0xFE, 0x00, 0x12, 0x8F, 0x9F])
    text, enc = detect_and_decode_html(un_decodable)
    assert isinstance(text, str)
    assert enc in ("utf-8", "gb18030", "shift_jis")


def test_pipeline_json_data_bypass():
    pipeline = ContentPipeline()
    raw_json = json.dumps({"status": "success", "data": [{"id": 1, "name": "item"}]})
    fetch_res = FetchResult(
        html=raw_json,
        url="https://api.example.com/v1/items",
        status_code=200,
        headers={"content-type": "application/json; charset=utf-8"},
        fetcher_type=FetcherType.HTTP,
    )
    doc = pipeline.process(fetch_res)
    assert doc is not None
    assert "```json" in doc.page_content
    assert '"status": "success"' in doc.page_content
    assert doc.metadata["url"] == "https://api.example.com/v1/items"


def test_pipeline_json_data_bypass_with_max_chars():
    pipeline = ContentPipeline()
    raw_json = json.dumps({"status": "success", "long_text": "a" * 500})
    fetch_res = FetchResult(
        html=raw_json,
        url="https://api.example.com/v1/items",
        status_code=200,
        headers={"content-type": "application/json"},
        fetcher_type=FetcherType.HTTP,
    )
    doc = pipeline.process(fetch_res, max_chars=100)
    assert doc is not None
    assert "[TRUNCATED]" in doc.page_content
    assert doc.metadata["was_truncated"] is True


def test_pipeline_xml_data_bypass():
    pipeline = ContentPipeline()
    raw_xml = "<rss version='2.0'><channel><title>News Feed</title></channel></rss>"
    fetch_res = FetchResult(
        html=raw_xml,
        url="https://example.com/feed.xml",
        status_code=200,
        headers={"content-type": "application/xml"},
        fetcher_type=FetcherType.HTTP,
    )
    doc = pipeline.process(fetch_res)
    assert doc is not None
    assert "```xml" in doc.page_content
    assert "News Feed" in doc.page_content


def test_pipeline_xml_data_bypass_with_max_chars():
    pipeline = ContentPipeline()
    raw_xml = "<root>" + ("<item>content</item>" * 50) + "</root>"
    fetch_res = FetchResult(
        html=raw_xml,
        url="https://example.com/feed.xml",
        status_code=200,
        headers={"content-type": "text/xml"},
        fetcher_type=FetcherType.HTTP,
    )
    doc = pipeline.process(fetch_res, max_chars=80)
    assert doc is not None
    assert "[TRUNCATED]" in doc.page_content
    assert doc.metadata["was_truncated"] is True
