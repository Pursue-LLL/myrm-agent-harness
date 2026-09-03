"""Unit tests for failure signature clustering and addressability derivation."""

from __future__ import annotations

import pytest

from myrm_agent_harness.eval.failure_clustering import (
    AddressabilityVerdict,
    FailureSignature,
    ProfilePatchProposal,
    SignatureCluster,
    cluster_failure_signatures,
    extract_query_intent,
    is_weak_model_tier,
    sanitize_failure_fingerprint,
)
from myrm_agent_harness.eval.protocols import (
    AgentResponse,
    EvalCase,
    EvalManifest,
    EvalResult,
    EvalTurnResult,
)
from myrm_agent_harness.eval.trajectory_analysis import FailureMode


def test_sanitize_failure_fingerprint():
    raw_stack = (
        'Error at 0x7ffd9b8210 File "/var/folders/3x/tmp/run_4920/test.py", line 42\n'
        "Temp cache path /var/folders/3x/tmp/run_4920/test.py\n"
        "UUID 12345678-1234-5678-1234-567812345678 crashed on line 105"
    )
    cleaned = sanitize_failure_fingerprint(raw_stack)
    assert "0x7ffd9b8210" not in cleaned
    assert "<HEX_ADDR>" in cleaned
    assert "12345678-1234-5678-1234-567812345678" not in cleaned
    assert "<UUID>" in cleaned
    assert "<TEMP_PATH>" in cleaned
    assert "line <N>" in cleaned


def test_extract_query_intent():
    assert extract_query_intent("SELECT * FROM users WHERE id = 1") == "sql_query"
    assert extract_query_intent("def solve_problem(): pass") == "code_generation"
    assert extract_query_intent("search for latest python 3.13 docs") == "web_search"
    assert extract_query_intent("prove Fermat's theorem") == "math_reasoning"
    assert extract_query_intent("read file /etc/hosts") == "file_io"
    assert extract_query_intent("hello there") == "general_task"


def test_is_weak_model_tier():
    assert is_weak_model_tier("qwen2.5-7b-instruct") is True
    assert is_weak_model_tier("llama-3.1-8b") is True
    assert is_weak_model_tier("gpt-4o-mini") is True
    assert is_weak_model_tier("claude-3-5-haiku") is True
    assert is_weak_model_tier("deepseek-v3") is False
    assert is_weak_model_tier("gpt-4o") is False


def test_cluster_failure_signatures_empty():
    res = EvalResult()
    clusters = cluster_failure_signatures(res)
    assert clusters == []


def test_cluster_failure_signatures_with_malformed_arguments():
    manifest = EvalManifest(
        model_provider="openai",
        model_id="qwen2.5-7b",
        harness_version="1.0.0",
        tool_policy=(),
        task_set_id="test_set",
        task_set_hash="hash",
        prompt_fingerprint="fp",
        budget_max_tokens=1000,
        timeout_seconds=30,
        created_at="now",
    )
    turns = [
        EvalTurnResult(
            case=EvalCase(message="Run SQL select * from users", expected_tools=()),
            response=AgentResponse(answer=""),
            assertion_passed=False,
            assertion_details="invalid_tool_call_arguments: unescaped quotes at line 14",
        ),
        EvalTurnResult(
            case=EvalCase(message="Run SQL select id from orders", expected_tools=()),
            response=AgentResponse(answer=""),
            assertion_passed=False,
            assertion_details="invalid_tool_call_arguments: unescaped quotes at line 99",
        ),
        # 1 passed turn
        EvalTurnResult(
            case=EvalCase(message="Simple ping", expected_tools=()),
            response=AgentResponse(answer="pong"),
            assertion_passed=True,
        ),
    ]
    eval_res = EvalResult(turn_results=turns, manifest=manifest)
    clusters = cluster_failure_signatures(eval_res)

    assert len(clusters) == 1
    c = clusters[0]
    assert c.signature.failure_mode == FailureMode.TOOL_ARGUMENT_MALFORMED
    assert c.case_count == 2
    assert c.verdict == AddressabilityVerdict.ADDRESSABLE
    assert c.patch_proposal is not None
    assert c.patch_proposal.path == "/capabilities/tool_repair/enabled"
    assert c.patch_proposal.value is True

    # Check to_dict serialization
    c_dict = c.to_dict()
    assert c_dict["case_count"] == 2
    assert c_dict["verdict"] == "addressable"
    assert c_dict["patch_proposal"]["op"] == "replace"


def test_cluster_failure_signatures_model_limit():
    manifest = EvalManifest(
        model_provider="openai",
        model_id="qwen2.5-7b",
        harness_version="1.0.0",
        tool_policy=(),
        task_set_id="test_math",
        task_set_hash="hash",
        prompt_fingerprint="fp",
        budget_max_tokens=1000,
        timeout_seconds=30,
        created_at="now",
    )
    # Intent misunderstanding on math with weak model -> MODEL_LIMIT
    turns = [
        EvalTurnResult(
            case=EvalCase(message="Solve complex math equation", expected_tools=()),
            response=AgentResponse(answer="Wrong answer"),
            assertion_passed=False,
            assertion_details="Semantic assertion failed: incorrect proof",
        ),
    ]
    eval_res = EvalResult(turn_results=turns, manifest=manifest)
    clusters = cluster_failure_signatures(eval_res)

    assert len(clusters) == 1
    c = clusters[0]
    assert c.verdict == AddressabilityVerdict.MODEL_LIMIT
    assert c.patch_proposal is not None
    assert c.patch_proposal.path == "/model_routing/complex_reasoning_model"
    assert c.patch_proposal.value == "deepseek-r1"
