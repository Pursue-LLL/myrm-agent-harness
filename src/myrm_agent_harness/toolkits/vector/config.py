"""Vector Store Configuration.

[INPUT]
(none — leaf module)

[OUTPUT]
DeploymentMode: Enum for embedded/remote deployment
VectorStoreConfig: Pydantic configuration model

[POS]
Generic vector store configuration. Defines deployment modes and connection parameters, backend-agnostic.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class DeploymentMode(StrEnum):
    """Vector store deployment mode.

    - EMBEDDED: Local file storage, zero external dependencies
    - REMOTE: Connect to server/cloud service
    """

    EMBEDDED = "embedded"
    REMOTE = "remote"


class VectorStoreConfig(BaseModel):
    """Vector store configuration.

    Example::

        # Embedded (development / sandbox)
        config = VectorStoreConfig(
            mode=DeploymentMode.EMBEDDED,
            local_path="./data/vectors",
        )

        # Remote (production / shared cluster)
        config = VectorStoreConfig(
            mode=DeploymentMode.REMOTE,
            url="http://localhost:6333",
            api_key="your-api-key",
        )
    """

    mode: DeploymentMode = Field(
        default=DeploymentMode.EMBEDDED,
        description="Deployment mode: 'embedded' (local file) or 'remote' (server/cloud)",
    )

    # Embedded mode
    local_path: str = Field(default="./data/vector_store", description="Local path for vector data (embedded mode)")

    # Remote mode
    url: str = Field(default="http://localhost:6333", description="Server URL (remote mode)")
    api_key: str | None = Field(default=None, description="API key (optional, for cloud deployment)")

    # Common
    default_collection_prefix: str = Field(default="default", description="Default prefix for collection names")
    embedding_dimension: int = Field(default=1536, description="Default embedding vector dimension")

    def get_collection_name(self, name: str) -> str:
        """Get full collection name with prefix."""
        if self.default_collection_prefix:
            return f"{self.default_collection_prefix}_{name}"
        return name
