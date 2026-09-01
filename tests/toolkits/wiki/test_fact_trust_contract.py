"""Unit tests for FactStatus and FactTrustPolicy contract."""

from pathlib import Path
import pytest

from myrm_agent_harness.toolkits.wiki.core.fact_trust_contract import (
    FactStatus,
    FactTrustPolicy,
    infer_fact_status_from_path,
    resolve_fact_status,
)


def test_infer_fact_status_from_path() -> None:
    assert infer_fact_status_from_path("wiki/concepts/architecture.md") == FactStatus.PUBLISHED_TRUTH
    assert infer_fact_status_from_path("wiki/truth/api_spec.md") == FactStatus.PUBLISHED_TRUTH
    assert infer_fact_status_from_path("wiki/drafts/rfc_new.md") == FactStatus.IN_PROGRESS_DRAFT
    assert infer_fact_status_from_path("wiki/archive/old_design.md") == FactStatus.DEPRECATED
    assert infer_fact_status_from_path("legacy/v1_spec.md") == FactStatus.DEPRECATED


def test_resolve_fact_status_frontmatter_override() -> None:
    content_explicit = "---\nfact_status: in_progress_draft\n---\n# Title\nBody"
    assert resolve_fact_status(content_explicit, file_path="wiki/truth/file.md") == FactStatus.IN_PROGRESS_DRAFT

    content_deprecated = "---\nfact_status: deprecated\n---\n# Title\nBody"
    assert resolve_fact_status(content_deprecated) == FactStatus.DEPRECATED

    content_publish_status_draft = "---\npublish_status: draft\n---\n# Title\nBody"
    assert resolve_fact_status(content_publish_status_draft) == FactStatus.IN_PROGRESS_DRAFT

    content_default = "# Plain markdown without frontmatter"
    assert resolve_fact_status(content_default, file_path="docs/drafts/foo.md") == FactStatus.IN_PROGRESS_DRAFT


def test_fact_trust_policy_multipliers() -> None:
    policy = FactTrustPolicy(truth_boost=1.5, draft_multiplier=0.2, deprecated_multiplier=0.05)
    assert policy.get_multiplier(FactStatus.PUBLISHED_TRUTH) == 1.5
    assert policy.get_multiplier(FactStatus.IN_PROGRESS_DRAFT) == 0.2
    assert policy.get_multiplier(FactStatus.DEPRECATED) == 0.05
