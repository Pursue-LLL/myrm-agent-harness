"""Agent Secret Backend Protocol.

[INPUT]
- (none)

[OUTPUT]
- AgentSecretBackend: Protocol for Agent Secret Storage Backend.

[POS]
Agent Secret Backend Protocol.
"""

from typing import Protocol


class AgentSecretBackend(Protocol):
    """Protocol for Agent Secret Storage Backend.

    Implementations must securely store key-value pairs associated with a specific agent.
    This protocol is used by the framework to decouple secret management from the execution engine.
    """

    def set_secret(self, agent_id: str, key_name: str, secret_value: str) -> None:
        """Store or update a secret for an agent.

        Args:
            agent_id: The ID of the agent
            key_name: The name of the secret (e.g., 'GITHUB_TOKEN')
            secret_value: The plain text secret value to be securely stored
        """
        ...

    def get_secret(self, agent_id: str, key_name: str) -> str | None:
        """Retrieve a decrypted secret for an agent.

        Args:
            agent_id: The ID of the agent
            key_name: The name of the secret

        Returns:
            The decrypted secret value, or None if not found
        """
        ...

    def delete_secret(self, agent_id: str, key_name: str) -> bool:
        """Delete a specific secret for an agent.

        Args:
            agent_id: The ID of the agent
            key_name: The name of the secret

        Returns:
            True if deleted, False if not found
        """
        ...

    def get_all_secrets(self, agent_id: str) -> dict[str, str]:
        """Retrieve all decrypted secrets for an agent.

        Args:
            agent_id: The ID of the agent

        Returns:
            A dictionary of all secrets (key_name -> secret_value)
        """
        ...

    def delete_all_secrets(self, agent_id: str) -> None:
        """Delete all secrets associated with an agent.

        Args:
            agent_id: The ID of the agent
        """
        ...
