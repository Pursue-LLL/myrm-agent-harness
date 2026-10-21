"""Unit tests for loop command parsing, formatting, and marker detection."""

from myrm_agent_harness.runtime.loop.parser import (
    build_wakeup_prompt,
    format_interval,
    is_loop_complete_response,
    parse_interval_token,
    parse_loop_args,
)
from myrm_agent_harness.runtime.loop.types import LOOP_COMPLETE_MARKER, LoopMode


def test_parse_interval_token() -> None:
    assert parse_interval_token("30s") == 30
    assert parse_interval_token("5m") == 300
    assert parse_interval_token("2h") == 7200
    assert parse_interval_token("1h30m") == 5400
    assert parse_interval_token("1h15m30s") == 4530
    assert parse_interval_token("invalid") is None
    assert parse_interval_token("0s") is None
    assert parse_interval_token("") is None


def test_format_interval() -> None:
    assert format_interval(30) == "30s"
    assert format_interval(60) == "1m"
    assert format_interval(90) == "1m30s"
    assert format_interval(3600) == "1h"
    assert format_interval(3665) == "1h1m5s"


def test_parse_loop_args_valid_cases() -> None:
    # Fixed interval
    cfg1 = parse_loop_args("5m check CI status --times 10")
    assert cfg1.is_valid
    assert cfg1.mode == LoopMode.INTERVAL
    assert cfg1.interval_seconds == 300
    assert cfg1.prompt == "check CI status"
    assert cfg1.times == 10
    assert cfg1.until == ""

    # Self-paced (omitted interval)
    cfg2 = parse_loop_args("keep an eye on migration and summarize progress")
    assert cfg2.is_valid
    assert cfg2.mode == LoopMode.SELF_PACED
    assert cfg2.interval_seconds is None
    assert cfg2.prompt == "keep an eye on migration and summarize progress"

    # With --until condition
    cfg3 = parse_loop_args("2m poll the queue --until queue depth reaches zero")
    assert cfg3.is_valid
    assert cfg3.interval_seconds == 120
    assert cfg3.prompt == "poll the queue"
    assert cfg3.until == "queue depth reaches zero"

    # Sugar 'every'
    cfg4 = parse_loop_args("every 10m run linting pass")
    assert cfg4.is_valid
    assert cfg4.interval_seconds == 600
    assert cfg4.prompt == "run linting pass"

    # Command with /loop prefix
    cfg5 = parse_loop_args("/loop 1m check cluster telemetry --times 5")
    assert cfg5.is_valid
    assert cfg5.mode == LoopMode.INTERVAL
    assert cfg5.interval_seconds == 60
    assert cfg5.prompt == "check cluster telemetry"
    assert cfg5.times == 5


def test_parse_loop_args_invalid_cases() -> None:
    cfg1 = parse_loop_args("")
    assert not cfg1.is_valid
    assert cfg1.error == "empty command"

    cfg2 = parse_loop_args("5m")
    assert not cfg2.is_valid
    assert "missing task prompt" in (cfg2.error or "")

    cfg3 = parse_loop_args("5m watch job --times 0")
    assert not cfg3.is_valid
    assert "--times expects a positive integer" in (cfg3.error or "")


def test_build_wakeup_prompt() -> None:
    prompt = build_wakeup_prompt(1, "check deploy", cadence_label="every 5m")
    assert "[/loop wakeup #1, every 5m]" in prompt
    assert "Recurring task: check deploy" in prompt
    assert LOOP_COMPLETE_MARKER in prompt

    until_prompt = build_wakeup_prompt(2, "watch queue", until="queue is empty")
    assert "Stop condition: queue is empty" in until_prompt


def test_is_loop_complete_response() -> None:
    assert is_loop_complete_response("Task finished successfully.\nLOOP_COMPLETE")
    assert is_loop_complete_response("  LOOP_COMPLETE.  ")
    assert is_loop_complete_response("All done!\n\nLOOP_COMPLETE\n")
    assert not is_loop_complete_response("Still processing...")
    assert not is_loop_complete_response("LOOP_COMPLETE_NOT_REALLY")
