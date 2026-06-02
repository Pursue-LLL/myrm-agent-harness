"""Eval Case Loader — load test cases from JSON files.

[INPUT]
- protocol::EvalCase, (POS: Protocol contract. Framework provides FileEventLogBackend; business layer may extend with SQLite / PostgreSQL implementations.)

[OUTPUT]
- load_cases(): single-turn case loader
- load_multi_turn_cases(): multi-turn case loader

[POS]
Convenience utilities for loading eval cases from JSON files.
Keeps the framework self-contained (no YAML dependency).
Business layer can implement custom loaders for other formats.

Expected JSON format for single-turn:
[
  {
    "message": "Search for Python tutorials",
    "expected_tools": ["web_search"],
    "require_all": false,
    "metadata": {"category": "search"}
  }
]

Expected JSON format for multi-turn:
[
  {
    "turns": [
      {"message": "Hello", "expected_tools": []},
      {"message": "Search for X", "expected_tools": ["web_search"]}
    ],
    "metadata": {"scenario": "greeting_then_search"}
  }
]
"""

from __future__ import annotations

import json
from pathlib import Path

from .protocols import EvalCase, MultiTurnEvalCase


def load_cases(path: str | Path) -> list[EvalCase]:
    """Load single-turn eval cases from a JSON file."""
    data = _read_json(path)
    return [_parse_case(item) for item in data]


def load_multi_turn_cases(path: str | Path) -> list[MultiTurnEvalCase]:
    """Load multi-turn eval cases from a JSON file. Automatically upgrades single-turn cases."""
    data = _read_json(path)
    result = []
    for item in data:
        if "turns" in item:
            result.append(
                MultiTurnEvalCase(
                    turns=[_parse_case(t) for t in item["turns"]],
                    metadata=item.get("metadata", {}),
                )
            )
        else:
            result.append(
                MultiTurnEvalCase(
                    turns=[_parse_case(item)],
                    metadata=item.get("metadata", {}),
                )
            )
    return result


def _read_json(path: str | Path) -> list[dict[str, object]]:
    p = Path(path)
    if not p.exists():
        msg = f"Eval case file not found: {p}"
        raise FileNotFoundError(msg)

    with p.open(encoding="utf-8") as f:
        # Support both JSON array and JSONL formats
        content = f.read().strip()
        if not content:
            return []

        if content.startswith("["):
            data = json.loads(content)
        else:
            data = [json.loads(line) for line in content.splitlines() if line.strip()]

    if not isinstance(data, list):
        msg = f"Eval case file must contain a JSON array or JSONL lines, got {type(data).__name__}"
        raise TypeError(msg)

    return data


def _parse_case(item: dict[str, object]) -> EvalCase:
    message = item.get("message")
    if not isinstance(message, str) or not message:
        msg = f"EvalCase requires non-empty 'message' string, got: {message!r}"
        raise ValueError(msg)

    expected_tools = item.get("expected_tools", [])
    if not isinstance(expected_tools, list):
        msg = f"'expected_tools' must be a list, got {type(expected_tools).__name__}"
        raise TypeError(msg)

    from .protocols import SandboxAssertion, SemanticAssertion, StateAssertion

    sandbox_assertions = []
    for a in item.get("sandbox_assertions", []):
        sandbox_assertions.append(
            SandboxAssertion(type=a.get("type"), target=a.get("target"), expected=a.get("expected"))
        )

    state_assertions = []
    for a in item.get("state_assertions", []):
        state_assertions.append(
            StateAssertion(type=a.get("type"), expected=a.get("expected"), threshold=a.get("threshold", 0.8))
        )

    semantic_assertions = []
    for a in item.get("semantic_assertions", []):
        semantic_assertions.append(
            SemanticAssertion(
                type=a.get("type", "llm_judge"), expected=a.get("expected"), threshold=a.get("threshold", 1.0)
            )
        )

    return EvalCase(
        message=message,
        expected_tools=[str(t) for t in expected_tools],
        require_all=bool(item.get("require_all", False)),
        sandbox_assertions=sandbox_assertions,
        state_assertions=state_assertions,
        semantic_assertions=semantic_assertions,
        metadata={str(k): str(v) for k, v in (item.get("metadata") or {}).items()},
    )
