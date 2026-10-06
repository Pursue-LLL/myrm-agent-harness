"""GLM XML tool-call parser: document-order pairing, single-tag recovery, anomalies."""

import json
import random
import re
import time

import pytest

from myrm_agent_harness.toolkits.llms.adapters.parsers.glm_xml import (
    _ARG_ELEMENTS,
    _TOOL_CALL_ELEMENT,
    _normalize_arg_tags,
    _parse_arg_pairs,
    _scan_elements,
)
from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import (
    _parse_glm_xml_format,
    parse_tool_calls,
)


def _args(call: dict) -> dict:
    return json.loads(call["function"]["arguments"])


def test_parse_glm_xml_normal_pairs_in_document_order():
    xml = """<tool_call>search_web
<arg_key>query</arg_key>
<arg_value>hello world</arg_value>
<arg_key>limit</arg_key>
<arg_value>5</arg_value>
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "search_web"
    assert _args(calls[0]) == {"query": "hello world", "limit": 5}


def test_parse_glm_xml_nested_json_value_preserved_verbatim():
    # The inner JSON is opaque payload; document-order scanning must keep it
    # attached to its own key instead of re-interpreting nested braces.
    xml = """<tool_call>t
<arg_key>opts</arg_key>
<arg_value>{"nested": {"k": 1}, "list": [1, 2]}</arg_value>
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert _args(calls[0]) == {"opts": {"nested": {"k": 1}, "list": [1, 2]}}


def test_parse_glm_xml_missing_open_value_tag_is_recovered():
    # Upstream (vLLM #49248) can drop an <arg_value> opening tag while the value
    # and its closer survive. The value is bound to the preceding key and `limit`'s
    # value must NOT shift onto `query`.
    xml = """<tool_call>search_web
<arg_key>query</arg_key>
hello world</arg_value>
<arg_key>limit</arg_key>
<arg_value>5</arg_value>
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert len(calls) == 1
    assert _args(calls[0]) == {"query": "hello world", "limit": 5}


def test_parse_glm_xml_missing_close_value_tag_is_recovered():
    # Ollama #14656: the closing </arg_value> is dropped; the value is bounded by
    # the block's own </tool_call>, so it is complete and must be kept.
    xml = """<tool_call>t
<arg_key>path</arg_key>
<arg_value>/tmp/x
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert len(calls) == 1
    assert _args(calls[0]) == {"path": "/tmp/x"}


def test_parse_glm_xml_missing_close_value_tag_before_next_key_is_recovered():
    xml = """<tool_call>t
<arg_key>path</arg_key>
<arg_value>/tmp/x
<arg_key>mode</arg_key>
<arg_value>r</arg_value>
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert _args(calls[0]) == {"path": "/tmp/x", "mode": "r"}


def test_parse_glm_xml_missing_open_tag_with_nested_json_value_recovers():
    xml = """<tool_call>t
<arg_key>opts</arg_key>
{"code": 7, "retry": true}</arg_value>
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert _args(calls[0]) == {"opts": {"code": 7, "retry": True}}


def test_parse_glm_xml_tool_name_inline_with_first_arg_is_extracted():
    # GLM-4.7 emits the function name directly before the first <arg_key> with no
    # newline; the name must not absorb the argument stream.
    xml = "<tool_call>read_file<arg_key>path</arg_key><arg_value>/a.txt</arg_value></tool_call>"
    calls = _parse_glm_xml_format(xml)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "read_file"
    assert _args(calls[0]) == {"path": "/a.txt"}


def test_parse_glm_xml_value_containing_key_like_text_is_not_split():
    # A value may legitimately contain the literal text ``<arg_key>``; pass 2 only
    # treats it as a new key when it is a *closed* ``<arg_key>…</arg_key>`` structure.
    xml = """<tool_call>t
<arg_key>template</arg_key>
<arg_value>emit <arg_key> inside the payload</arg_value>
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert _args(calls[0]) == {"template": "emit <arg_key> inside the payload"}


def test_parse_glm_xml_orphan_value_without_key_stays_dropped():
    xml = """<tool_call>t
<arg_value>loose</arg_value>
<arg_key>k</arg_key>
<arg_value>v</arg_value>
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert _args(calls[0]) == {"k": "v"}


def test_parse_glm_xml_well_formed_bytes_unchanged():
    # Recovery must be a no-op on well-formed output.
    xml = """<tool_call>t
<arg_key>a</arg_key>
<arg_value>1</arg_value>
</tool_call>"""
    normalized, anomalies = _normalize_arg_tags("<arg_key>a</arg_key><arg_value>1</arg_value>")
    assert normalized == "<arg_key>a</arg_key><arg_value>1</arg_value>"
    assert anomalies == []
    assert _args(_parse_glm_xml_format(xml)[0]) == {"a": 1}


def test_parse_glm_xml_trailing_key_without_value_is_dropped():
    xml = """<tool_call>t
<arg_key>a</arg_key>
<arg_value>1</arg_value>
<arg_key>b</arg_key>
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert _args(calls[0]) == {"a": 1}


def test_parse_glm_xml_multiple_calls_get_distinct_indexes_and_ids():
    xml = """<tool_call>first
<arg_key>a</arg_key>
<arg_value>1</arg_value>
</tool_call>
<tool_call>second
<arg_key>b</arg_key>
<arg_value>2</arg_value>
</tool_call>"""
    calls = _parse_glm_xml_format(xml)
    assert [c["function"]["name"] for c in calls] == ["first", "second"]
    assert [c["index"] for c in calls] == [0, 1]
    assert len({c["id"] for c in calls}) == 2


def test_parse_glm_xml_dispatched_through_facade():
    reasoning = "<tool_call>read_file\n<arg_key>path</arg_key>\n<arg_value>/a.txt</arg_value>\n</tool_call>"
    calls = parse_tool_calls({"reasoning_content": reasoning})
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "read_file"


def test_parse_glm_xml_no_tags_returns_empty():
    assert _parse_glm_xml_format("") == []
    assert _parse_glm_xml_format("plain reasoning without tags") == []


# ---------------------------------------------------------------------------
# Tag scanning
# ---------------------------------------------------------------------------

_TAG_SOUP_TOKENS = (
    "<arg_key>",
    "</arg_key>",
    "<arg_value>",
    "</arg_value>",
    "<tool_call>",
    "</tool_call>",
    "k",
    "v",
    "\n",
    "<",
    "<arg_",
)


def _tag_soup(rng: random.Random) -> str:
    return "".join(rng.choice(_TAG_SOUP_TOKENS) for _ in range(rng.randint(0, 16)))


def test_scan_elements_dangling_opener_does_not_hide_later_elements():
    text = "<arg_key>lost <arg_value>kept</arg_value>"

    assert _scan_elements(text, _ARG_ELEMENTS) == [("value", "kept")]


def test_scan_elements_element_swallows_tags_nested_in_its_payload():
    text = "<tool_call>a<tool_call>b</tool_call>c</tool_call>"

    assert _scan_elements(text, _TOOL_CALL_ELEMENT) == [("tool_call", "a<tool_call>b")]


def test_scan_elements_matches_the_lazy_regex_it_replaces():
    """The scanner is a drop-in for the DOTALL ``findall`` regexes: same elements on arbitrary tag soup."""
    rng = random.Random(20261007)
    arg_regex = re.compile(r"<arg_(key|value)>(.*?)</arg_\1>", re.DOTALL)
    call_regex = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)

    for _ in range(3_000):
        text = _tag_soup(rng)
        assert _scan_elements(text, _ARG_ELEMENTS) == arg_regex.findall(text), text
        assert [payload for _, payload in _scan_elements(text, _TOOL_CALL_ELEMENT)] == call_regex.findall(text), text


# ---------------------------------------------------------------------------
# Dropped <arg_value> tags
# ---------------------------------------------------------------------------

_VALUES = ("1", "hello world", "multi\nline value", '{"a": [1, 2]}', "/tmp/x")


def _random_pairs(rng: random.Random) -> list[tuple[str, str]]:
    return [(f"key{index}", rng.choice(_VALUES)) for index in range(rng.randint(1, 6))]


def _render_pairs(pairs: list[tuple[str, str]], dropped: tuple[int, str] | None = None) -> str:
    """Render pairs as GLM XML, omitting one ``<arg_value>`` tag: ``dropped = (pair index, tag)``."""
    parts: list[str] = []
    for index, (key, value) in enumerate(pairs):
        opener = "" if dropped == (index, "<arg_value>") else "<arg_value>"
        closer = "" if dropped == (index, "</arg_value>") else "</arg_value>"
        parts.append(f"<arg_key>{key}</arg_key>\n{opener}{value}{closer}\n")
    return "".join(parts)


def test_well_formed_blocks_are_never_rewritten():
    rng = random.Random(1)

    for _ in range(500):
        block = _render_pairs(_random_pairs(rng))
        assert _normalize_arg_tags(block) == (block, [])


@pytest.mark.parametrize("dropped_tag", ["<arg_value>", "</arg_value>"])
def test_any_single_dropped_value_tag_is_restored_without_shifting_other_pairs(dropped_tag: str):
    rng = random.Random(2)

    for _ in range(500):
        pairs = _random_pairs(rng)
        damaged = _render_pairs(pairs, dropped=(rng.randrange(len(pairs)), dropped_tag))

        normalized, normalize_anomalies = _normalize_arg_tags(damaged)
        recovered, pairing_anomalies = _parse_arg_pairs(normalized)

        assert recovered == [(key, value.strip()) for key, value in pairs], damaged
        assert normalize_anomalies
        assert pairing_anomalies == []


# ---------------------------------------------------------------------------
# Degenerate streams
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("<tool_call>t\n" + "<arg_key>k" * 8_000 + "</tool_call>", id="dangling-arg-key-openers"),
        pytest.param("<tool_call>x\n" * 8_000, id="dangling-tool-call-openers"),
        pytest.param(
            "<tool_call>t\n" + "<arg_key>k</arg_key><arg_value>v" * 20_000 + "</tool_call>",
            id="unclosed-arg-value-after-every-key",
        ),
        pytest.param("<tool_call>t\n" + "</arg_value>" * 40_000 + "</tool_call>", id="stray-arg-value-closers"),
    ],
)
def test_a_model_stuck_repeating_a_tag_cannot_stall_the_parser(text: str):
    # Every scan is linear: these inputs take milliseconds, while a lazy-regex or
    # rescan-per-tag implementation needs seconds (quadratic) and would freeze the event loop.
    started = time.perf_counter()

    _parse_glm_xml_format(text)

    assert time.perf_counter() - started < 1.0
