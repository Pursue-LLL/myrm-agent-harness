"""Backend implementations — profiles, secrets, and skills adapters.

Import from subpackages directly (this package does not re-export symbols):

  - ``backends.profiles``: AgentProfile, AgentProfileBackend, LocalProfileBackend, ...
  - ``backends.secrets``: AgentSecretBackend, LocalSecretBackend, ...
  - ``backends.skills``: SkillBackend (factory), SkillBackendProtocol, SkillMetadata (via types), ...

For stable extension-point Protocols, prefer ``myrm_agent_harness.api.protocols``.

For storage backends, use ``toolkits.storage`` directly.
"""
