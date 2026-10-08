"""Core always-on vault secret dynamic redaction pipeline.

[INPUT]
- Text strings, structured tool returns, user inbound messages, and credential vaults.

[OUTPUT]
- Redacted strings and structured data stripped of vault keys, ambient secrets, and tokens.

[POS]
- Harness core security primitive in core/security/vault_secret_redaction/pipeline.py.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping, Sequence

from myrm_agent_harness.core.security.credential_vault import CredentialVault

from .stream_scrubber import SecretStreamScrubber, strip_ansi_codes
from .types import (
    RedactionResult,
    SecretEntry,
    SecretSourceType,
    VaultSecretRedactionConfig,
)

# Known environment variables that commonly contain sensitive credentials
AMBIENT_ENV_NAME_HINTS: frozenset[str] = frozenset(
    [
        "API_KEY",
        "ACCESS_TOKEN",
        "AUTH_TOKEN",
        "SECRET_KEY",
        "SECRET",
        "PASSWORD",
        "PASSWD",
        "BEARER_TOKEN",
        "CLIENT_SECRET",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GITHUB_TOKEN",
        "SLACK_BOT_TOKEN",
        "MYRM_API_KEY",
    ]
)


class AlwaysOnVaultSecretRedactor:
    """Always-on secret dynamic redactor bridging CredentialVault, env, and runtime inputs."""

    def __init__(
        self, config: VaultSecretRedactionConfig | None = None
    ) -> None:
        self._config: VaultSecretRedactionConfig = (
            config if config is not None else VaultSecretRedactionConfig()
        )
        self._lock: threading.Lock = threading.Lock()
        self._secrets: dict[str, SecretEntry] = {}
        self._sorted_cache: list[tuple[str, str, str]] = []
        self._cache_dirty: bool = True
        self._match_stats: dict[str, int] = {}

    @property
    def config(self) -> VaultSecretRedactionConfig:
        """Current redaction configuration."""
        return self._config

    def update_config(self, config: VaultSecretRedactionConfig) -> None:
        """Update configuration and mark cache dirty."""
        with self._lock:
            self._config = config
            self._cache_dirty = True

    def register_secret(
        self,
        name: str,
        value: str,
        source: SecretSourceType = SecretSourceType.DYNAMIC_CAPTURED,
        mask: str | None = None,
    ) -> bool:
        """Register a sensitive credential into the active redaction set.

        Returns True if registered, or False if skipped due to length constraint.
        """
        trimmed = value.strip()
        if len(trimmed) < self._config.min_secret_length:
            return False

        with self._lock:
            self._secrets[name] = SecretEntry(
                name=name, value=trimmed, source=source, mask=mask
            )
            self._cache_dirty = True
            if name not in self._match_stats:
                self._match_stats[name] = 0
            return True

    def unregister_secret(self, name: str) -> bool:
        """Remove a secret from the active redaction set."""
        with self._lock:
            if name in self._secrets:
                del self._secrets[name]
                self._cache_dirty = True
                return True
            return False

    def list_secret_names(self) -> list[str]:
        """List all registered secret labels."""
        with self._lock:
            return sorted(self._secrets.keys())

    def clear(self) -> None:
        """Clear all registered secrets."""
        with self._lock:
            self._secrets.clear()
            self._sorted_cache.clear()
            self._cache_dirty = True
            self._match_stats.clear()

    def sync_from_credential_vault(self, vault: CredentialVault) -> int:
        """Hydrate redaction dictionary from CredentialVault entries."""
        registered_count = 0
        with self._lock:
            for label, entry in vault._credentials.items():
                if entry.password:
                    trimmed_pw = entry.password.strip()
                    if len(trimmed_pw) >= self._config.min_secret_length:
                        self._secrets[f"vault_password_{label}"] = SecretEntry(
                            name=f"vault_password_{label}",
                            value=trimmed_pw,
                            source=SecretSourceType.VAULT,
                        )
                        registered_count += 1
                if entry.totp_seed:
                    trimmed_totp = entry.totp_seed.strip()
                    if len(trimmed_totp) >= self._config.min_secret_length:
                        self._secrets[f"vault_totp_{label}"] = SecretEntry(
                            name=f"vault_totp_{label}",
                            value=trimmed_totp,
                            source=SecretSourceType.VAULT,
                        )
                        registered_count += 1
            if registered_count > 0:
                self._cache_dirty = True
        return registered_count

    def collect_ambient_env_secrets(
        self, env_dict: Mapping[str, str] | None = None
    ) -> int:
        """Collect credentials from ambient environment variables matching hints."""
        source_env = os.environ if env_dict is None else env_dict
        collected = 0
        for k, v in source_env.items():
            upper_k = k.upper()
            if any(
                hint in upper_k for hint in AMBIENT_ENV_NAME_HINTS
            ) and self.register_secret(
                name=k, value=v, source=SecretSourceType.AMBIENT_ENV
            ):
                collected += 1
        return collected

    def _ensure_cache_fresh(self) -> list[tuple[str, str, str]]:
        """Return sorted (name, value, mask) tuples longest-first."""
        if not self._cache_dirty:
            return self._sorted_cache

        entries: list[tuple[str, str, str]] = []
        for entry in self._secrets.values():
            mask = (
                entry.mask
                if entry.mask is not None
                else self._config.mask_template.format(name=entry.name)
            )
            entries.append((entry.name, entry.value, mask))

        # Longest value first to prevent prefix collision
        entries.sort(key=lambda item: len(item[1]), reverse=True)
        self._sorted_cache = entries
        self._cache_dirty = False
        return self._sorted_cache

    def redact_text(self, text: str) -> RedactionResult:
        """Perform dynamic redaction on raw text string."""
        if not text:
            return RedactionResult(clean_content="", redacted_count=0)

        with self._lock:
            sorted_entries = list(self._ensure_cache_fresh())

        processed = (
            strip_ansi_codes(text) if self._config.strip_ansi else text
        )
        total_redacted = 0
        matched_names: list[str] = []

        for name, val, mask in sorted_entries:
            if val in processed:
                count = processed.count(val)
                processed = processed.replace(val, mask)
                total_redacted += count
                matched_names.append(name)
                with self._lock:
                    self._match_stats[name] = (
                        self._match_stats.get(name, 0) + count
                    )

        return RedactionResult(
            clean_content=processed,
            redacted_count=total_redacted,
            matched_secrets=matched_names,
        )

    def _sanitize_data_structure(
        self, obj: object
    ) -> tuple[object, int, list[str]]:
        """Recursively scrub sensitive values from nested structures."""
        if isinstance(obj, str):
            res = self.redact_text(obj)
            return res.clean_content, res.redacted_count, res.matched_secrets

        if isinstance(obj, Mapping):
            new_map: dict[str, object] = {}
            tot_count = 0
            matched: list[str] = []
            for k, v in obj.items():
                s_key = str(k)
                clean_v, count, sub_matched = self._sanitize_data_structure(v)
                new_map[s_key] = clean_v
                tot_count += count
                matched.extend(sub_matched)
            return new_map, tot_count, matched

        if isinstance(obj, Sequence) and not isinstance(
            obj, (str, bytes, bytearray)
        ):
            new_list: list[object] = []
            tot_count = 0
            matched = []
            for item in obj:
                clean_item, count, sub_matched = self._sanitize_data_structure(
                    item
                )
                new_list.append(clean_item)
                tot_count += count
                matched.extend(sub_matched)
            return new_list, tot_count, matched

        return obj, 0, []

    def redact_tool_return(
        self, content: object
    ) -> tuple[object, RedactionResult]:
        """Redact tool invocation output across strings and nested structures."""
        clean_obj, count, matched = self._sanitize_data_structure(content)
        result = RedactionResult(
            clean_content=str(clean_obj),
            redacted_count=count,
            matched_secrets=list(dict.fromkeys(matched)),
        )
        return clean_obj, result

    def redact_user_message(
        self, content: object
    ) -> tuple[object, RedactionResult]:
        """Redact inbound user message payload before saving or sending to LLMs."""
        clean_obj, count, matched = self._sanitize_data_structure(content)
        result = RedactionResult(
            clean_content=str(clean_obj),
            redacted_count=count,
            matched_secrets=list(dict.fromkeys(matched)),
        )
        return clean_obj, result

    def create_stream_scrubber(self) -> SecretStreamScrubber:
        """Create a dedicated stream scrubber holding back boundary collisions."""
        with self._lock:
            sorted_entries = self._ensure_cache_fresh()
            pairs = [(name, val) for name, val, _ in sorted_entries]
        return SecretStreamScrubber(
            secret_entries=pairs,
            mask_template=self._config.mask_template,
            strip_ansi=self._config.strip_ansi,
        )

    def get_stats(self) -> dict[str, int]:
        """Retrieve match counts for each registered secret."""
        with self._lock:
            return dict(self._match_stats)
