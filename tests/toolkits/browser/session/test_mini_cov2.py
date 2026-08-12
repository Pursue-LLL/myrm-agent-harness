from myrm_agent_harness.toolkits.browser.session.structured_extractor import _extract_json_from_text


def test_mini():
    assert _extract_json_from_text('{"a": 1}', expect_array=False) == {"a": 1}
