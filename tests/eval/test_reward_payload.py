"""Tests for suite_judge reward/JUnit payload parsing."""

import pytest


def test_parse_reward_result_variants() -> None:
    """parse_reward_result handles bare numbers, score keys, and rejections."""
    from myrm_agent_harness.eval.suite_judge import parse_reward_result

    assert parse_reward_result("0.8") == 0.8
    assert parse_reward_result('{"score": 0.75}') == 0.75
    assert parse_reward_result('{"reward_score": 1}') == 1.0
    assert parse_reward_result('{"reward": true}') is None
    assert parse_reward_result('{"reward": "high"}') is None
    assert parse_reward_result("<xml>") is None
    assert parse_reward_result("") is None


def test_parse_reward_result_official_fields() -> None:
    """parse_reward_result honors official WBBench reward payload keys."""
    from myrm_agent_harness.eval.suite_judge import parse_reward_result

    # reward.json emitted by the official scorer.py carries overall/test_pass_rate.
    assert parse_reward_result('{"overall": 0.85}') == 0.85
    assert parse_reward_result('{"test_pass_rate": 0.66}') == 0.66
    # Precedence follows the official reader: reward → overall → test_pass_rate → score.
    assert parse_reward_result('{"score": 0.4, "reward": 0.9}') == 0.9
    assert parse_reward_result('{"score": 0.4, "overall": 0.7}') == 0.7
    assert parse_reward_result('{"test_pass_rate": 0.5, "score": 0.9}') == 0.5
    # Non-dict/non-numeric payloads still reject cleanly.
    assert parse_reward_result('{"overall": "high"}') is None
    # Bare numeric text: the Code script_verifier writes str(reward["overall"]).
    assert parse_reward_result("0.85") == 0.85
    assert parse_reward_result("1.0\n") == 1.0
    assert parse_reward_result("high") is None


def test_counts_from_reward() -> None:
    """_counts_from_reward derives (passed, total) like the official reader."""
    from myrm_agent_harness.eval.suite_judge import _counts_from_reward

    assert _counts_from_reward('{"tests_passed": 8, "tests_total": 10}') == (8, 10)
    assert _counts_from_reward(
        '{"tests": [{"name": "a", "passed": true}, {"name": "b", "passed": false}]}'
    ) == (1, 2)
    assert _counts_from_reward('{"tests": [{"passed": "true"}, {"passed": "no"}]}') == (1, 2)
    assert _counts_from_reward('{"tests_passed": 3, "tests_total": 10, "tests": []}') == (3, 10)
    # A shrunken suite cannot inflate the ratio: passed clamps to total.
    assert _counts_from_reward('{"tests_passed": 12, "tests_total": 10}') == (10, 10)
    assert _counts_from_reward('{"message": "ok"}') is None
    assert _counts_from_reward("0.8") is None
    assert _counts_from_reward("<xml>") is None
    assert _counts_from_reward("") is None


@pytest.mark.asyncio
async def test_read_reward_payload_falls_back_to_alternate(executor, tmp_path) -> None:
    """A scorer writing score.json is picked up when result_file names reward.json."""
    from myrm_agent_harness.eval.suite_judge import _read_reward_payload

    (tmp_path / "score.json").write_text('{"score": 0.9}')
    raw, path = await _read_reward_payload(f"{tmp_path}/reward.json", executor)
    assert raw == '{"score": 0.9}'
    assert path == f"{tmp_path}/score.json"


@pytest.mark.asyncio
async def test_read_reward_payload_skips_unscorable(executor, tmp_path) -> None:
    """An unscorable score.json yields to a scorable sibling reward.json."""
    from myrm_agent_harness.eval.suite_judge import _read_reward_payload

    (tmp_path / "score.json").write_text('{"message": "ok"}')
    (tmp_path / "reward.json").write_text('{"reward": 0.75}')
    raw, path = await _read_reward_payload(f"{tmp_path}/score.json", executor)
    assert raw == '{"reward": 0.75}'
    assert path == f"{tmp_path}/reward.json"


@pytest.mark.asyncio
async def test_read_reward_payload_keeps_unscorable_raw(executor, tmp_path) -> None:
    """With no scorable sibling, the first readable payload is kept for detail."""
    from myrm_agent_harness.eval.suite_judge import _read_reward_payload

    (tmp_path / "reward.json").write_text('{"message": "ok"}')
    raw, path = await _read_reward_payload(f"{tmp_path}/reward.json", executor)
    assert raw == '{"message": "ok"}'
    assert path == f"{tmp_path}/reward.json"


@pytest.mark.asyncio
async def test_read_reward_payload_falls_back_to_reward_txt(executor, tmp_path) -> None:
    """A script_verifier writing reward.txt is picked up from a reward.json result_file."""
    from myrm_agent_harness.eval.suite_judge import _read_reward_payload

    (tmp_path / "reward.txt").write_text("0.66")
    raw, path = await _read_reward_payload(f"{tmp_path}/reward.json", executor)
    assert raw == "0.66"
    assert path == f"{tmp_path}/reward.txt"


@pytest.mark.asyncio
async def test_read_reward_payload_missing_all(executor, tmp_path) -> None:
    """No readable candidate yields (None, declared path)."""
    from myrm_agent_harness.eval.suite_judge import _read_reward_payload

    raw, path = await _read_reward_payload(f"{tmp_path}/reward.json", executor)
    assert raw is None
    assert path == f"{tmp_path}/reward.json"


def test_parse_junit_result_malformed() -> None:
    """Malformed or non-numeric JUnit attributes degrade to zero counts."""
    from myrm_agent_harness.eval.suite_judge import parse_junit_result

    assert parse_junit_result("<not-xml") == (0, 0)
    assert parse_junit_result("<testsuite tests='abc' failures='x'/>") == (0, 0)
    assert parse_junit_result("<testsuite tests='' />") == (0, 0)


def test_parse_junit_result_multi_suite() -> None:
    """Multiple testsuites under a testsuites root are aggregated."""
    from myrm_agent_harness.eval.suite_judge import parse_junit_result

    xml = (
        "<testsuites>"
        "<testsuite tests='3' failures='1' errors='0'/>"
        "<testsuite tests='2' failures='0' errors='1'/>"
        "</testsuites>"
    )
    assert parse_junit_result(xml) == (3, 5)

