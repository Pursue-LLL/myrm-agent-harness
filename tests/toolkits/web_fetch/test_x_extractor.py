"""Unit tests for Twitter/X post fast-path extractor."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from myrm_agent_harness.toolkits.web_fetch.extractors.x_extractor import (
    _format_oembed_document,
    _format_tweet_document,
    extract_status_info,
    extract_x_post,
    is_x_url,
)


def test_is_x_url():
    assert is_x_url("https://x.com/karpathy/status/1234567890123456789")
    assert is_x_url("https://twitter.com/sama/status/987654321")
    assert is_x_url("https://mobile.twitter.com/user/status/1122334455")
    assert is_x_url("https://fxtwitter.com/user/status/1122334455")
    assert is_x_url("https://vxtwitter.com/user/status/1122334455")
    assert is_x_url("https://fixupx.com/user/status/1122334455")
    assert not is_x_url("https://x.com/home")
    assert not is_x_url("https://youtube.com/watch?v=123")
    assert not is_x_url("")


def test_extract_status_info():
    info = extract_status_info("https://x.com/karpathy/status/1234567890123456789?s=20")
    assert info == ("karpathy", "1234567890123456789")

    info2 = extract_status_info("https://twitter.com/sama/status/998877")
    assert info2 == ("sama", "998877")

    assert extract_status_info("https://google.com") is None


def test_format_tweet_document():
    tweet = {
        "author": {"name": "Andrej Karpathy", "screen_name": "karpathy"},
        "text": "Deep dive into LLM tokenizers and transformers.",
        "created_at": "Thu Aug 27 12:00:00 +0000 2026",
        "likes": 5000,
        "retweets": 1200,
        "replies": 350,
        "media": {
            "photos": [{"url": "https://pbs.twimg.com/media/example.jpg"}],
        },
    }
    doc = _format_tweet_document(tweet, "https://x.com/karpathy/status/123")
    assert "**Andrej Karpathy** (@karpathy)" in doc.page_content
    assert "Deep dive into LLM tokenizers" in doc.page_content
    assert "![Image](https://pbs.twimg.com/media/example.jpg)" in doc.page_content
    assert "5000 喜欢" in doc.page_content
    assert doc.metadata["author"] == "Andrej Karpathy"
    assert doc.metadata["screen_name"] == "karpathy"
    assert doc.metadata["source_type"] == "x_post"
    assert doc.metadata["likes"] == 5000


def test_format_oembed_document():
    oembed = {
        "author_name": "Sam Altman",
        "author_url": "https://twitter.com/sama",
        "html": "<blockquote><p>AGI is coming.</p>&mdash; Sam Altman (@sama)</blockquote>",
    }
    doc = _format_oembed_document(oembed, "https://x.com/sama/status/456")
    assert "**Sam Altman**" in doc.page_content
    assert "AGI is coming" in doc.page_content
    assert doc.metadata["source_type"] == "x_post_oembed"


@pytest.mark.asyncio
async def test_extract_x_post_fxtwitter_success():
    fake_response = {
        "code": 200,
        "message": "OK",
        "tweet": {
            "author": {"name": "Test User", "screen_name": "testuser"},
            "text": "Hello world from test!",
            "created_at": "Thu Aug 27 12:00:00 +0000 2026",
            "likes": 10,
            "retweets": 2,
        },
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.OpenerDirector.open", return_value=mock_resp):
        doc = await extract_x_post("https://x.com/testuser/status/123456")
        assert doc is not None
        assert "Hello world from test!" in doc.page_content
        assert doc.metadata["screen_name"] == "testuser"
