"""In-Memory Profile Backend Implementation.

Non-persistent, memory-only storage for agent profiles.
Useful for testing, single-run scripts, or ephemeral environments.

[INPUT]
- .types::AgentProfile (POS: Agent Profile 数据类型定义)
- .exceptions::ProfileAlreadyExistsError, ProfileNotFoundError (POS: Profile 后端异常类型)
- .protocols::AgentProfileBackend (POS: Agent Profile 存储后端协议)

[OUTPUT]
- InMemoryProfileBackend: Dict-backed in-memory profile store.

[POS]
内存 Profile 后端。进程结束即丢失，适用于测试和临时场景。
"""

from myrm_agent_harness.backends.profiles.exceptions import ProfileAlreadyExistsError, ProfileNotFoundError
from myrm_agent_harness.backends.profiles.types import AgentProfile

from .protocols import AgentProfileBackend


class InMemoryProfileBackend(AgentProfileBackend):
    """Store agent profiles in memory (dict).

    Data is lost when the Python process terminates.
    """

    def __init__(self) -> None:
        self._storage: dict[str, AgentProfile] = {}

    def list_profiles(self) -> list[AgentProfile]:
        return list(self._storage.values())

    def get_profile(self, profile_id: str) -> AgentProfile | None:
        return self._storage.get(profile_id)

    def create_profile(self, profile: AgentProfile) -> AgentProfile:
        if profile.id in self._storage:
            raise ProfileAlreadyExistsError(profile.id)
        self._storage[profile.id] = profile
        return profile

    def update_profile(self, profile: AgentProfile) -> AgentProfile:
        if profile.id not in self._storage:
            raise ProfileNotFoundError(profile.id)
        self._storage[profile.id] = profile
        return profile

    def delete_profile(self, profile_id: str) -> bool:
        if profile_id in self._storage:
            del self._storage[profile_id]
            return True
        return False
