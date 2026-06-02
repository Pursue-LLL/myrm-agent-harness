"""Test fixtures for web_search tests"""

from unittest.mock import Mock, patch

import pytest

from myrm_agent_harness.toolkits.retriever.reranker import RerankerConfig


@pytest.fixture
def mock_reranker_service():
    """Mock reranker service instance"""
    return Mock()


@pytest.fixture
def mock_reranker_config():
    """Real reranker config for testing"""
    return RerankerConfig(model="cohere/rerank-v3.5", api_key="test-key")


@pytest.fixture
def patch_get_reranker_service(mock_reranker_service):
    """Patch get_reranker_service to return mock"""
    with patch("myrm_agent_harness.toolkits.retriever.reranker.get_reranker_service") as mock_get:
        mock_get.return_value = mock_reranker_service
        yield mock_get
