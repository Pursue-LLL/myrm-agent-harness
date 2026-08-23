"""Unit tests for workflow fingerprinting in cron engine."""

import pytest
from myrm_agent_harness.toolkits.cron.engine.fingerprint import (
    canonicalize_text,
    compute_workflow_fingerprint,
)


def test_canonicalize_text_basic():
    assert canonicalize_text("") == ""
    assert canonicalize_text(None) == ""
    assert canonicalize_text("   hello   world   \n  \t") == "hello world"
    assert canonicalize_text("fetch  news   everyday") == "fetch news everyday"


def test_compute_workflow_fingerprint_deterministic():
    fp1 = compute_workflow_fingerprint(
        prompt="Daily summary of AI news",
        agent_id="agent_1",
        workflow_template_id="tmpl_123",
        tools_allowed=["web_search_tool", "net_fetch"],
    )
    fp2 = compute_workflow_fingerprint(
        prompt="  Daily   summary of   AI news \n",
        agent_id="agent_1",
        workflow_template_id="tmpl_123",
        tools_allowed=["net_fetch", "web_search_tool"],  # Order permutation
    )
    assert len(fp1) == 64
    assert fp1 == fp2


def test_compute_workflow_fingerprint_distinct():
    fp1 = compute_workflow_fingerprint(
        prompt="Daily summary of AI news",
        agent_id="agent_1",
    )
    fp2 = compute_workflow_fingerprint(
        prompt="Daily summary of Financial news",
        agent_id="agent_1",
    )
    fp3 = compute_workflow_fingerprint(
        prompt="Daily summary of AI news",
        agent_id="agent_2",
    )
    assert fp1 != fp2
    assert fp1 != fp3
