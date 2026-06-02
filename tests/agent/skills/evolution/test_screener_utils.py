"""More tests for EvolutionScreener."""

from myrm_agent_harness.agent.skills.evolution.pipeline.screener import EvolutionScreener


def test_extract_error_signals():
    screener = EvolutionScreener(store=None)
    error_log = "HTTP 404 timeout ValueError connection"
    signals = screener._extract_error_signals(error_log)
    assert "404" in signals["http_status"]
    assert "ValueError" in signals["exception_types"]
    assert "timeout" in signals["error_keywords"]
    assert "connection" in signals["error_keywords"]


def test_parse_llm_response():
    screener = EvolutionScreener(store=None)

    dec, reason, conf = screener._parse_llm_response("YES\nReason: fix it")
    assert dec is True
    assert "fix it" in reason

    dec, reason, conf = screener._parse_llm_response("NO\nReason: too hard")
    assert dec is False
    assert "too hard" in reason

    dec, reason, conf = screener._parse_llm_response('{"approved": true, "reason": "ok", "confidence": 0.9}')
    assert dec is True
    assert reason == "ok"
    assert conf == 0.9

    dec, reason, conf = screener._parse_llm_response("CONFIRMED it's good")
    assert dec is True
    assert "good" in reason

    dec, reason, conf = screener._parse_llm_response("REJECTED it's bad")
    assert dec is False
    assert "bad" in reason
