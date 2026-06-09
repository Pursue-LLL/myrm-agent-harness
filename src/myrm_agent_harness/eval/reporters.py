"""Eval Reporters — format and persist evaluation results.

[INPUT]
- protocol::EvalResult (POS: Eval framework type system and AgentExecutor protocol.)

[OUTPUT]
- JsonlReporter: writes results as JSON Lines.
- MarkdownReporter: writes results as a human-readable Markdown report.

[POS]
Provides out-of-the-box reporting capabilities for the Eval framework.
Ensures developers can easily persist and review test results without
writing custom parsing logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocols import EvalResult


class JsonlReporter:
    """Writes evaluation results to a JSON Lines file."""

    def __init__(self, output_path: str | Path) -> None:
        self.output_path = Path(output_path)

    def report(self, result: EvalResult) -> None:
        """Write the EvalResult to the output path."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        total_tokens_sum = 0
        total_time_secs = 0.0
        case_count = len(result.turn_results)

        with self.output_path.open("w", encoding="utf-8") as f:
            # Collect per-turn data first for summary aggregation
            turn_lines: list[str] = []
            for turn in result.turn_results:
                time_secs = turn.timings.total_ms / 1000.0
                total_time_secs += time_secs
                turn_tokens = turn.response.token_usage.get("total_tokens", 0)
                total_tokens_sum += turn_tokens

                turn_data = {
                    "type": "turn",
                    "passed": turn.assertion_passed,
                    "case": {
                        "message": turn.case.message,
                        "expected_tools": turn.case.expected_tools,
                        "state_assertions": [
                            {"type": a.type, "expected": a.expected, "threshold": a.threshold}
                            for a in getattr(turn.case, "state_assertions", [])
                        ],
                    },
                    "actual_tools": turn.response.tools_called,
                    "actual_output": turn.response.answer,
                    "usage": turn.response.token_usage,
                    "time_secs": round(time_secs, 3),
                    "details": turn.assertion_details,
                    "error": turn.error,
                }
                turn_lines.append(json.dumps(turn_data, ensure_ascii=False))

            summary = {
                "type": "summary",
                "total_cases": result.total_cases,
                "pass_count": result.pass_count,
                "fail_count": result.fail_count,
                "error_count": result.error_count,
                "skip_count": result.skip_count,
                "pass_rate": result.pass_rate,
                "all_passed": result.all_passed,
                "total_ms": result.total_ms,
                "avg_time_secs": round(total_time_secs / case_count, 3) if case_count else 0.0,
                "avg_total_tokens": round(total_tokens_sum / case_count) if case_count else 0,
            }
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
            for line in turn_lines:
                f.write(line + "\n")


class MarkdownReporter:
    """Writes evaluation results to a Markdown file."""

    def __init__(self, output_path: str | Path) -> None:
        self.output_path = Path(output_path)

    def report(self, result: EvalResult) -> None:
        """Write the EvalResult to the output path."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        total_tokens = result.total_tokens
        total_cost = result.total_cost

        lines = [
            "# Evaluation Report",
            "",
            "## Summary",
            "",
            f"- **Total Cases**: {result.total_cases}",
            f"- **Passed**: {result.pass_count}",
            f"- **Failed**: {result.fail_count}",
            f"- **Errors**: {result.error_count}",
            f"- **Skipped**: {result.skip_count}",
            f"- **Pass Rate**: {result.pass_rate * 100:.1f}%",
            f"- **Total Time**: {result.total_ms:.0f}ms",
        ]

        if total_tokens > 0:
            avg_tokens = total_tokens // result.total_cases if result.total_cases else 0
            lines.append(f"- **Total Tokens**: {total_tokens:,} (avg {avg_tokens:,}/case)")
        if total_cost > 0:
            lines.append(f"- **Total Cost**: ${total_cost:.4f}")

        lines.extend(
            [
                "",
                "## Details",
                "",
            ]
        )

        for i, turn in enumerate(result.turn_results, 1):
            status = " PASS" if turn.assertion_passed else (" FAIL" if turn.assertion_passed is False else " SKIP")
            if turn.error:
                status = " ERROR"

            lines.extend(
                [
                    f"### Case {i}: {status}",
                    "",
                    f"**Message**: `{turn.case.message}`",
                    "",
                    f"- **Expected Tools**: `{turn.case.expected_tools}`",
                    f"- **Tools Called**: `{turn.response.tools_called}`",
                    f"- **Time**: `{turn.timings.total_ms:.0f}ms`",
                    "",
                ]
            )

            if turn.assertion_details:
                lines.extend(
                    [
                        "**Assertion Details**:",
                        "```text",
                        turn.assertion_details,
                        "```",
                        "",
                    ]
                )

            if turn.error:
                lines.extend(
                    [
                        "**Error**:",
                        "```text",
                        turn.error,
                        "```",
                        "",
                    ]
                )

        with self.output_path.open("w", encoding="utf-8") as f:
            f.write("\n".join(lines))
