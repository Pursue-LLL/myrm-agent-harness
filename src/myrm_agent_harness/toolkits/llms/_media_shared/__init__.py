"""Shared data types, normalization, and security utilities for media generation.

[OUTPUT]
- types: MediaTaskState, ModeCapabilities, ProviderModeCapabilities, NormalizationRecord, SizeSpec
- normalization: resolve_closest_ratio, resolve_closest_size, resolve_closest_duration, normalize_params
- security: validate_media_url, sanitize_filename
- task_store: MediaTask, MediaTaskStore, InMemoryMediaTaskStore, FileMediaTaskStore

[POS]
Shared across video/ and image/ modules. Keeps media-specific logic
separate from the global security/ and agent/ namespaces.
"""
