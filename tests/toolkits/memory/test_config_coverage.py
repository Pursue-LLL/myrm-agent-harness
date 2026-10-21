"""Coverage tests for config.py."""

from myrm_agent_harness.toolkits.memory.config import MemoryConfig, RetrievalConfig, _normalize_model_name
from myrm_agent_harness.toolkits.memory.types import MemoryType


class TestNormalizeModelName:
    """Test model name normalization."""

    def test_normalize_openai_model(self) -> None:
        """Test normalizing OpenAI model name."""
        result = _normalize_model_name("openai/BAAI/bge-m3")
        assert result == "openai-baai-bge-m3"

    def test_normalize_with_special_chars(self) -> None:
        """Test normalizing with special characters."""
        result = _normalize_model_name("model@v1.0/test_name")
        assert result == "model-v1-0-test-name"

    def test_normalize_long_name_truncation(self) -> None:
        """Test that long names are truncated to 40 chars."""
        long_name = "a" * 100
        result = _normalize_model_name(long_name)
        assert len(result) == 40

    def test_normalize_strips_leading_trailing_hyphens(self) -> None:
        """Test that leading/trailing hyphens are stripped."""
        result = _normalize_model_name("--model-name--")
        assert result == "model-name"

    def test_normalize_lowercase_conversion(self) -> None:
        """Test that uppercase is converted to lowercase."""
        result = _normalize_model_name("UPPERCASE/Model")
        assert result == "uppercase-model"


class TestMemoryConfigProperties:
    """Test MemoryConfig property methods."""

    def test_semantic_collection_name(self) -> None:
        """Test semantic collection name generation."""
        config = MemoryConfig(embedding_model="BAAI/bge-m3")
        assert config.semantic_collection == "memory_semantic_baai-bge-m3"

    def test_episodic_collection_name(self) -> None:
        """Test episodic collection name generation."""
        config = MemoryConfig(embedding_model="openai/text-embedding-3-small")
        assert config.episodic_collection == "memory_episodic_openai-text-embedding-3-small"

    def test_custom_collection_prefix(self) -> None:
        """Test custom collection prefix."""
        config = MemoryConfig(embedding_model="test-model", collection_prefix="custom")
        assert config.semantic_collection == "custom_semantic_test-model"
        assert config.episodic_collection == "custom_episodic_test-model"

    def test_collection_name_with_special_chars(self) -> None:
        """Test collection name with special characters in model."""
        config = MemoryConfig(embedding_model="model@v1.0/test")
        assert "model-v1-0-test" in config.semantic_collection
        assert "model-v1-0-test" in config.episodic_collection


class TestRetrievalConfigDefaults:
    """Test RetrievalConfig default values."""

    def test_default_values(self) -> None:
        """Test all default configuration values."""
        config = RetrievalConfig()
        assert config.rrf_k == 60
        assert config.correction_penalty == 0.1
        assert config.frequency_saturation == 50

    def test_default_type_weights(self) -> None:
        """Test default type weights."""
        config = RetrievalConfig()
        assert config.type_weights[MemoryType.PROFILE] == 1.0
        assert config.type_weights[MemoryType.SEMANTIC] == 1.0
        assert config.type_weights[MemoryType.EPISODIC] == 0.8
        assert config.type_weights[MemoryType.PROCEDURAL] == 0.9

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = RetrievalConfig(rrf_k=80, correction_penalty=0.2, frequency_saturation=100)
        assert config.rrf_k == 80
        assert config.correction_penalty == 0.2
        assert config.frequency_saturation == 100

    def test_custom_type_weights(self) -> None:
        """Test custom type weights."""
        custom_weights = {
            MemoryType.PROFILE: 1.5,
            MemoryType.SEMANTIC: 1.2,
            MemoryType.EPISODIC: 0.6,
            MemoryType.PROCEDURAL: 0.7,
        }
        config = RetrievalConfig(type_weights=custom_weights)
        assert config.type_weights == custom_weights

    def test_config_immutability(self) -> None:
        """Test that config is frozen (immutable)."""
        config = RetrievalConfig()
        try:
            config.rrf_k = 100
            assert False, "Should not be able to modify frozen config"
        except AttributeError:
            pass


class TestMemoryConfigDefaults:
    """Test MemoryConfig default values."""

    def test_default_values(self) -> None:
        """Test all default configuration values."""
        config = MemoryConfig(embedding_model="test-model")
        assert config.collection_prefix == "memory"
        assert config.default_search_limit == 10
        assert config.similarity_threshold == 0.5
        assert config.forgetting_interval == 10
        assert config.bm25_top_k == 50
        assert config.bm25_max_corpus_size == 5000

    def test_default_retrieval_config(self) -> None:
        """Test default retrieval config is created."""
        config = MemoryConfig(embedding_model="test-model")
        assert isinstance(config.retrieval, RetrievalConfig)
        assert config.retrieval.rrf_k == 60

    def test_custom_retrieval_config(self) -> None:
        """Test custom retrieval config."""
        retrieval = RetrievalConfig(rrf_k=80)
        config = MemoryConfig(embedding_model="test-model", retrieval=retrieval)
        assert config.retrieval.rrf_k == 80

    def test_config_immutability(self) -> None:
        """Test that config is frozen (immutable)."""
        config = MemoryConfig(embedding_model="test-model")
        try:
            config.bm25_top_k = 100
            assert False, "Should not be able to modify frozen config"
        except AttributeError:
            pass
