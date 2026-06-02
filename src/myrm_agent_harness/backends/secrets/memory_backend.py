"""In-Memory Secret Backend Implementation.

This backend provides a non-persistent, memory-only storage for agent secrets.
It is useful for testing, single-run scripts, or when the execution environment
does not require persistent secret storage.

[INPUT]
- (none)

[OUTPUT]
- InMemorySecretBackend: Store agent secrets in memory (dict).

[POS]
In-Memory Secret Backend Implementation.
"""

from collections import defaultdict

from .protocols import AgentSecretBackend


class InMemorySecretBackend(AgentSecretBackend):
    """Store agent secrets in memory (dict).

    Data is lost when the Python process terminates.
    """

    def __init__(self):
        """Initialize the In-Memory Secret Backend."""
        # Mapping of agent_id -> {key_name: secret_value}
        self._storage: dict[str, dict[str, str]] = defaultdict(dict)

    def set_secret(self, agent_id: str, key_name: str, secret_value: str) -> None:
        """Store or update a secret for an agent in memory."""
        self._storage[agent_id][key_name] = secret_value

    def get_secret(self, agent_id: str, key_name: str) -> str | None:
        """Retrieve a secret for an agent from memory."""
        return self._storage.get(agent_id, {}).get(key_name)

    def delete_secret(self, agent_id: str, key_name: str) -> bool:
        """Delete a specific secret for an agent from memory."""
        agent_secrets = self._storage.get(agent_id)
        if agent_secrets and key_name in agent_secrets:
            del agent_secrets[key_name]
            # Clean up empty agent dicts
            if not agent_secrets:
                del self._storage[agent_id]
            return True
        return False

    def get_all_secrets(self, agent_id: str) -> dict[str, str]:
        """Retrieve all secrets for an agent from memory."""
        # Return a copy to prevent accidental mutation of internal state
        return dict(self._storage.get(agent_id, {}))

    def delete_all_secrets(self, agent_id: str) -> None:
        """Delete all secrets associated with an agent from memory."""
        if agent_id in self._storage:
            del self._storage[agent_id]
