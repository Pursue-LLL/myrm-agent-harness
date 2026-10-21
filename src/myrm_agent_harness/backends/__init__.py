"""Backend contracts and adapters — profiles, secrets, and skills.

Import from subpackages directly (this package does not re-export symbols):

  - ``backends.profiles``: AgentProfile, AgentProfileBackend, BuiltInAgent
  - ``backends.secrets``: AgentSecretBackend, external secret reference helpers
  - ``backends.skills``: SkillBackend (factory), SkillBackendProtocol, SkillMetadata (via types), ...

For stable extension-point Protocols, prefer ``myrm_agent_harness.api.protocols``.

For storage backends, use ``toolkits.storage`` directly.

[INPUT]
- (none — package entry point)

[OUTPUT]
- (no re-exports; consumers import from subpackages directly)

[POS]
Backend package root. Aggregates profile, secrets, and skills adapter subpackages.
"""
