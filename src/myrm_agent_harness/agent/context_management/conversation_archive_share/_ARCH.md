# conversation_archive_share

Architecture and module inventory for the `conversation_archive_share` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting conversation archive and share types, exporter, gateway, archiver, and facade suite |
| `archive_share_types.py` | Domain models and contracts for conversation shareable snapshots and tiered cold archiving |
| `sanitized_snapshot_exporter.py` | Sanitized conversation snapshot exporter redacting credentials and computing signatures |
| `signed_share_gateway.py` | Signed ephemeral share gateway verifying HMAC signatures and TTL expirations |
| `tiered_cold_storage_archiver.py` | Tiered cold storage archiver with lossless compression and instant wakeup |
| `conversation_shareable_snapshot_suite.py` | Unified facade suite coordinating conversation shareable snapshots and tiered cold archiving |
