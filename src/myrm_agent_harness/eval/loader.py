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
    "on_turn_fail": "abort",
    "metadata": {"scenario": "greeting_then_search"}
  }
]
"""

from __future__ import annotations

import json
from pathlib import Path

from .protocols import EvalCase, EvalCaseSplit, MultiTurnEvalCase


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
            kwargs: dict[str, object] = {
                "turns": [_parse_case(t) for t in item["turns"]],
                "metadata": item.get("metadata", {}),
            }
            if "on_turn_fail" in item:
                otf = item["on_turn_fail"]
                if otf not in ("continue", "skip_remaining", "abort"):
                    msg = f"on_turn_fail must be 'continue', 'skip_remaining', or 'abort', got: {otf!r}"
                    raise ValueError(msg)
                kwargs["on_turn_fail"] = otf
            result.append(MultiTurnEvalCase(**kwargs))
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

    from .protocols import (
        CompactionAssertion,
        PostEpisodeAssertion,
        RetrievalAssertion,
        SandboxAssertion,
        SemanticAssertion,
        StateAssertion,
    )

    sandbox_assertions = []
    for a in item.get("sandbox_assertions", []):
        sandbox_assertions.append(
            SandboxAssertion(
                type=a.get("type"),
                target=a.get("target"),
                expected=a.get("expected"),
                result_file=a.get("result_file"),
                timeout=a.get("timeout"),
            )
        )

    state_assertions = []
    for a in item.get("state_assertions", []):
        state_assertions.append(
            StateAssertion(
                type=a.get("type"),
                expected=a.get("expected"),
                threshold=a.get("threshold", 0.8),
            )
        )

    semantic_assertions = []
    for a in item.get("semantic_assertions", []):
        semantic_assertions.append(
            SemanticAssertion(
                type=a.get("type", "llm_judge"),
                expected=a.get("expected"),
                threshold=a.get("threshold", 1.0),
                judge_prompt=a.get("judge_prompt"),
                judge_model=a.get("judge_model"),
                judge_api_key=a.get("judge_api_key"),
                judge_api_base=a.get("judge_api_base"),
            )
        )

    compaction_assertions = []
    for a in item.get("compaction_assertions", []):
        compaction_assertions.append(
            CompactionAssertion(
                type=a.get("type", "compaction_fidelity"),
                expected_constraints=tuple(
                    str(x) for x in a.get("expected_constraints", ())
                ),
                forbidden_claims=tuple(str(x) for x in a.get("forbidden_claims", ())),
                required_artifacts=tuple(
                    str(x) for x in a.get("required_artifacts", ())
                ),
                expected_tools=tuple(str(x) for x in a.get("expected_tools", ())),
                min_fidelity_score=float(a.get("min_fidelity_score", 0.8)),
            )
        )

    retrieval_assertions = []
    for a in item.get("retrieval_assertions", []):
        retrieval_assertions.append(
            RetrievalAssertion(
                type=a.get("type", "retrieval_quality"),
                expected_spans=tuple(str(x) for x in a.get("expected_spans", ())),
                expected_doc_ids=tuple(str(x) for x in a.get("expected_doc_ids", ())),
                min_recall=float(a.get("min_recall", 1.0)),
                max_duplicate_rate=(
                    float(a["max_duplicate_rate"])
                    if a.get("max_duplicate_rate") is not None
                    else None
                ),
                min_distinct_sources=(
                    int(a["min_distinct_sources"])
                    if a.get("min_distinct_sources") is not None
                    else None
                ),
                top_k=int(a.get("top_k", 5)),
                strip_headers=bool(a.get("strip_headers", True)),
            )
        )

    post_episode_assertions = []
    for a in item.get("post_episode_assertions", []):
        post_episode_assertions.append(
            PostEpisodeAssertion(
                assertion_id=str(a.get("assertion_id", "post_ep")),
                assertion_type=str(a.get("assertion_type", "hidden_test_suite")),
                command=str(a.get("command", "")),
                expected_output=str(a.get("expected_output", "")),
                timeout_seconds=int(a.get("timeout_seconds", 300)),
                is_hidden=bool(a.get("is_hidden", True)),
                metadata=dict(a.get("metadata") or {}),
            )
        )

    return EvalCase(
        message=message,
        expected_tools=[str(t) for t in expected_tools],
        require_all=bool(item.get("require_all", False)),
        sandbox_assertions=sandbox_assertions,
        state_assertions=state_assertions,
        semantic_assertions=semantic_assertions,
        retrieval_assertions=retrieval_assertions,
        compaction_assertions=compaction_assertions,
        post_episode_assertions=post_episode_assertions,
        canary_protected=bool(item.get("canary_protected", False)),
        canary_token=str(item.get("canary_token", "")),
        metadata={str(k): str(v) for k, v in (item.get("metadata") or {}).items()},
    )
