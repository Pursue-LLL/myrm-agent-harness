"""Artifact type mappings — re-export from core.artifacts.

All definitions now live in ``myrm_agent_harness.core.artifacts.constants``.
This module re-exports them for backward compatibility within agent/.
"""

from myrm_agent_harness.core.artifacts.constants import *  # noqa: F403
from myrm_agent_harness.core.artifacts.constants import (
    _EXTRA_BINARY_EXTENSIONS as _EXTRA_BINARY_EXTENSIONS,
)
from myrm_agent_harness.core.artifacts.constants import (
    _EXTRA_DOCUMENT_EXTENSIONS as _EXTRA_DOCUMENT_EXTENSIONS,
)
from myrm_agent_harness.core.artifacts.constants import (
    ACTIVE_CONTENT_MIME_TYPES as ACTIVE_CONTENT_MIME_TYPES,
)
from myrm_agent_harness.core.artifacts.constants import (
    EXTENSION_TO_ARTIFACT_TYPE as EXTENSION_TO_ARTIFACT_TYPE,
)
from myrm_agent_harness.core.artifacts.constants import (
    EXTENSION_TO_LANGUAGE as EXTENSION_TO_LANGUAGE,
)
from myrm_agent_harness.core.artifacts.constants import (
    MIME_TO_ARTIFACT_TYPE as MIME_TO_ARTIFACT_TYPE,
)
from myrm_agent_harness.core.artifacts.constants import (
    ArtifactMappings as ArtifactMappings,
)
from myrm_agent_harness.core.artifacts.constants import (
    ArtifactType as ArtifactType,
)
from myrm_agent_harness.core.artifacts.constants import (
    get_all_mappings as get_all_mappings,
)
from myrm_agent_harness.core.artifacts.constants import (
    infer_artifact_type_from_extension as infer_artifact_type_from_extension,
)
from myrm_agent_harness.core.artifacts.constants import (
    infer_artifact_type_from_mime as infer_artifact_type_from_mime,
)
from myrm_agent_harness.core.artifacts.constants import (
    infer_language_from_extension as infer_language_from_extension,
)
from myrm_agent_harness.core.artifacts.constants import (
    is_active_content as is_active_content,
)
from myrm_agent_harness.core.artifacts.constants import (
    is_text_content as is_text_content,
)
