"""Agent Profile Backend Protocol.

Defines the storage protocol for Agent Profiles. The framework provides
local file and in-memory implementations; business layers can implement
database-backed versions.

[INPUT]
- .types::AgentProfile (POS: Agent Profile 数据类型定义)
- .exceptions::ProfileAlreadyExistsError, ProfileNotFoundError (POS: Profile 后端异常类型)

[OUTPUT]
- AgentProfileBackend: Protocol for Agent Profile storage backends.

[POS]
Agent Profile 存储后端协议。定义 CRUD 契约，解耦框架与具体存储实现。
"""

from typing import Protocol

from myrm_agent_harness.backends.profiles.types import AgentProfile


class AgentProfileBackend(Protocol):
    """Protocol for Agent Profile Storage Backend.

    Implementations must securely store and retrieve AgentProfile objects.
    """

    def list_profiles(self) -> list[AgentProfile]:
        """List all available profiles.

        Returns:
            A list of AgentProfile objects.
        """
        ...

    def get_profile(self, profile_id: str) -> AgentProfile | None:
        """Retrieve a specific profile by ID.

        Args:
            profile_id: The unique identifier of the profile.

        Returns:
            The AgentProfile object, or None if not found.
        """
        ...

    def create_profile(self, profile: AgentProfile) -> AgentProfile:
        """Create a new profile.

        Args:
            profile: The AgentProfile object to create.

        Returns:
            The created AgentProfile object.

        Raises:
            ProfileAlreadyExistsError: If a profile with the same ID already exists.
        """
        ...

    def update_profile(self, profile: AgentProfile) -> AgentProfile:
        """Update an existing profile.

        Args:
            profile: The AgentProfile object to update.

        Returns:
            The updated AgentProfile object.

        Raises:
            ProfileNotFoundError: If the profile does not exist.
        """
        ...

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a specific profile.

        Args:
            profile_id: The unique identifier of the profile to delete.

        Returns:
            True if the profile was deleted, False if it was not found.
        """
        ...
