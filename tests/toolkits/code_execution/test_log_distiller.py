"""Unit tests for TerminalLogDistiller.

Tests short output passthrough, ANSI stripping, progress churn filtering,
error anchor context extraction, and high compression ratio efficiency.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.utils.log_distiller import (
    TerminalLogDistiller,
    extract_terminal_prompt,
)


def test_short_output_passthrough() -> None:
    distiller = TerminalLogDistiller(passthrough_threshold_lines=80)
    raw = "total 16\n-rw-r--r-- 1 user staff 120 Aug 26 12:00 package.json\n-rw-r--r-- 1 user staff 540 Aug 26 12:00 README.md"
    result = distiller.distill(raw, exit_code=0, raw_log_path="/tmp/cmd_1.log")

    assert result.is_passthrough is True
    assert result.raw_line_count == 3
    assert result.distilled_line_count == 3
    assert result.compression_ratio == 0.0
    assert "package.json" in result.distilled_text
    assert result.exit_code == 0
    assert result.raw_log_path == "/tmp/cmd_1.log"


def test_ansi_and_carriage_return_cleansing() -> None:
    distiller = TerminalLogDistiller(passthrough_threshold_lines=10)
    # Generate 30 lines with ANSI color codes and carriage returns
    lines = [f"\x1b[32m[INFO]\x1b[0m Starting step {i}\r" for i in range(30)]
    lines.append("\x1b[31mnpm ERR! code ETIMEDOUT\x1b[0m")
    lines.append("\x1b[31mnpm ERR! syscall connect\x1b[0m")
    raw = "\n".join(lines)

    result = distiller.distill(raw, exit_code=1)

    assert result.is_passthrough is False
    assert "\x1b[32m" not in result.distilled_text
    assert "\r" not in result.distilled_text
    assert "NPM_ERROR" in result.extracted_error_signals
    assert "NETWORK_TIMEOUT" in result.extracted_error_signals
    assert "npm ERR! code ETIMEDOUT" in result.distilled_text


def test_massive_progress_churn_distillation() -> None:
    distiller = TerminalLogDistiller(default_max_lines=50, passthrough_threshold_lines=50)

    # Simulate 500 lines of npm/docker download progress
    raw_lines: list[str] = ["Building package dependencies..."]
    for i in range(1, 400):
        raw_lines.append(f"[{i % 100}%] downloading: {i * 10} kB/s ...")
    raw_lines.append("Analyzing configuration files...")
    raw_lines.append("CRITICAL: Error occurred in reverse proxy listener:")
    raw_lines.append("HTTP 403 Forbidden: Host not in trustedHosts list")
    raw_lines.append("Aborting server daemon...")
    for i in range(405, 500):
        raw_lines.append(f"Progress: [====>     ] {i}/500")
    raw_lines.append("Process terminated with exit code 1")

    raw = "\n".join(raw_lines)
    result = distiller.distill(raw, exit_code=1, raw_log_path=".myrm/tee/cmd_deploy.log")

    assert result.is_passthrough is False
    assert result.raw_line_count == len(raw_lines)
    assert result.distilled_line_count < 60
    assert result.compression_ratio > 0.85
    assert "HTTP_403_FORBIDDEN" in result.extracted_error_signals
    assert "HTTP 403 Forbidden: Host not in trustedHosts list" in result.distilled_text
    assert "[DISTILLED LOG:" in result.distilled_text
    assert "raw_log: .myrm/tee/cmd_deploy.log" in result.distilled_text
    assert "exit_code: 1" in result.distilled_text


def test_multiple_error_signals_anchoring() -> None:
    distiller = TerminalLogDistiller(default_max_lines=60, passthrough_threshold_lines=20)

    raw_lines: list[str] = [f"Init step {i}" for i in range(30)]
    raw_lines.append("Error: listen EADDRINUSE: address already in use :::8080")
    raw_lines.append("Failed to bind socket")
    for i in range(30):
        raw_lines.append(f"Subsystem polling attempt {i}...")
    raw_lines.append("Traceback (most recent call last):")
    raw_lines.append("  File 'app.py', line 42, in connect")
    raw_lines.append("ConnectionRefusedError: [Errno 111] Connection refused")
    for i in range(20):
        raw_lines.append(f"Cleaning up worker {i}...")

    raw = "\n".join(raw_lines)
    result = distiller.distill(raw, exit_code=1)

    assert "SOCKET_EADDRINUSE" in result.extracted_error_signals
    assert "PYTHON_TRACEBACK" in result.extracted_error_signals
    assert "SOCKET_ECONNREFUSED" in result.extracted_error_signals
    assert "EADDRINUSE" in result.distilled_text
    assert "ConnectionRefusedError" in result.distilled_text


def test_terminal_prompt_returns_none_without_interactive_prompt() -> None:
    assert extract_terminal_prompt([]) is None
    assert extract_terminal_prompt(["npm install", "added 12 packages"]) is None
    assert extract_terminal_prompt(["1) first", "2) second"]) is None


def test_terminal_prompt_extracts_confirmation_options() -> None:
    prompt = extract_terminal_prompt(["Installing dependencies…", "Proceed? [y/N]"])

    assert prompt is not None
    assert prompt.kind == "confirm"
    assert prompt.question == "Proceed?"
    assert [(option.id, option.label, option.value) for option in prompt.options] == [
        ("confirm-1", "y", "y"),
        ("confirm-2", "N", "N"),
    ]
    assert prompt.default_value == "N"
    assert prompt.to_dict() == {
        "kind": "confirm",
        "question": "Proceed?",
        "default_value": "N",
        "options": [
            {"id": "confirm-1", "label": "y", "value": "y", "submit": True},
            {"id": "confirm-2", "label": "N", "value": "N", "submit": True},
        ],
    }


def test_terminal_prompt_extracts_numbered_choice() -> None:
    lines = [
        "Select the deployment target:",
        "1) staging",
        "2) production",
        "Enter choice [1-2]:",
    ]
    prompt = extract_terminal_prompt(lines)

    assert prompt is not None
    assert prompt.kind == "choice"
    assert prompt.question == "Select the deployment target:"
    assert [(option.id, option.label, option.value) for option in prompt.options] == [
        ("choice-1", "staging", "1"),
        ("choice-2", "production", "2"),
    ]
    assert prompt.to_dict()["options"][0]["submit"] is True
    assert prompt.default_value is None


def test_terminal_prompt_extracts_press_enter_action() -> None:
    prompt = extract_terminal_prompt(["Copying files…", "Press ENTER to continue"])

    assert prompt is not None
    assert prompt.kind == "action"
    assert prompt.question == "Press ENTER to continue"
    assert [(option.id, option.label, option.value) for option in prompt.options] == [
        ("action-continue", "Continue", ""),
    ]


def test_terminal_prompt_rejects_keyboard_only_menus() -> None:
    assert (
        extract_terminal_prompt(
            [
                "Use arrow keys to move:",
                "❯ staging",
                "  production",
            ]
        )
        is None
    )
    assert (
        extract_terminal_prompt(
            [
                "Select packages:",
                "[ ] staging tools",
                "[x] production tools",
            ]
        )
        is None
    )
    assert (
        extract_terminal_prompt(
            [
                "Continue?",
                "y\x00",
            ]
        )
        is None
    )
