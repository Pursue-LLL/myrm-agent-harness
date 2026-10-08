"""Sensitive file path patterns and blacklist matching engine."""

from __future__ import annotations

import fnmatch
import os
import re

from .types import SensitiveFileCategory, SensitivePathRule

_CANONICAL_RULES: list[SensitivePathRule] = [
    # 1. Environment secrets
    SensitivePathRule(
        rule_id="env_files",
        pattern=".env*",
        category=SensitiveFileCategory.ENV_SECRET,
        description="Environment secrets and configuration (.env, .env.local, .env.prod)",
    ),
    # 2. Private cryptographic keys & certificates
    SensitivePathRule(
        rule_id="private_keys_pem",
        pattern="*.pem",
        category=SensitiveFileCategory.PRIVATE_KEY,
        description="PEM encoded certificates and private keys",
    ),
    SensitivePathRule(
        rule_id="private_keys_key",
        pattern="*.key",
        category=SensitiveFileCategory.PRIVATE_KEY,
        description="Private key files (*.key)",
    ),
    SensitivePathRule(
        rule_id="private_keys_pkcs",
        pattern="*.p12",
        category=SensitiveFileCategory.PRIVATE_KEY,
        description="PKCS#12 certificate bundles (*.p12, *.pfx)",
    ),
    SensitivePathRule(
        rule_id="ssh_id_rsa",
        pattern="*id_rsa*",
        category=SensitiveFileCategory.PRIVATE_KEY,
        description="SSH RSA private key pairs",
    ),
    SensitivePathRule(
        rule_id="ssh_id_ed25519",
        pattern="*id_ed25519*",
        category=SensitiveFileCategory.PRIVATE_KEY,
        description="SSH Ed25519 private key pairs",
    ),
    # 3. Password managers & vault files
    SensitivePathRule(
        rule_id="bitwarden_cache",
        pattern="*bitwarden*",
        category=SensitiveFileCategory.PASSWORD_VAULT,
        description="Bitwarden desktop/CLI cache and data files",
    ),
    SensitivePathRule(
        rule_id="onepassword_vault",
        pattern="*1password*",
        category=SensitiveFileCategory.PASSWORD_VAULT,
        description="1Password vault and local databases",
    ),
    SensitivePathRule(
        rule_id="keepass_vault",
        pattern="*.kdbx",
        category=SensitiveFileCategory.PASSWORD_VAULT,
        description="KeePass password databases",
    ),
    SensitivePathRule(
        rule_id="myrm_vault_db",
        pattern="*.myrm/vault*",
        category=SensitiveFileCategory.PASSWORD_VAULT,
        description="Myrm host vault database and encrypted stores",
    ),
    SensitivePathRule(
        rule_id="vault_sqlite",
        pattern="*vault*.db",
        category=SensitiveFileCategory.PASSWORD_VAULT,
        description="Encrypted vault database stores",
    ),
    # 4. Cloud and CLI credentials
    SensitivePathRule(
        rule_id="aws_credentials",
        pattern="*.aws/credentials*",
        category=SensitiveFileCategory.CLOUD_CREDENTIAL,
        description="AWS CLI credentials file",
    ),
    SensitivePathRule(
        rule_id="kube_config",
        pattern="*.kube/config*",
        category=SensitiveFileCategory.CLOUD_CREDENTIAL,
        description="Kubernetes cluster config credentials",
    ),
    SensitivePathRule(
        rule_id="docker_config",
        pattern="*.docker/config.json*",
        category=SensitiveFileCategory.CLOUD_CREDENTIAL,
        description="Docker hub auth credentials",
    ),
    SensitivePathRule(
        rule_id="git_credentials",
        pattern="*.git-credentials*",
        category=SensitiveFileCategory.CLOUD_CREDENTIAL,
        description="Git plaintext credential store",
    ),
    # 5. OAuth and auth token caches
    SensitivePathRule(
        rule_id="oauth_tokens",
        pattern="*oauth_token*.json",
        category=SensitiveFileCategory.OAUTH_CACHE,
        description="OAuth token storage cache",
    ),
    SensitivePathRule(
        rule_id="auth_tokens",
        pattern="*auth_token*",
        category=SensitiveFileCategory.SYSTEM_AUTH,
        description="Authentication session tokens",
    ),
]


class SensitivePathDenyRules:
    """Evaluates target file paths against canonical sensitive file blacklist rules."""

    def __init__(self, custom_rules: list[SensitivePathRule] | None = None) -> None:
        self.rules: list[SensitivePathRule] = list(_CANONICAL_RULES)
        if custom_rules:
            self.rules.extend(custom_rules)

    def match_path(self, target_path: str) -> SensitivePathRule | None:
        """Check if target file path matches any sensitive deny rule."""
        norm_path = self.normalize_path(target_path)
        base_name = os.path.basename(norm_path).lower()
        lowered_path = norm_path.lower()

        for rule in self.rules:
            pat = rule.pattern.lower()
            if rule.is_regex:
                if re.search(pat, lowered_path):
                    return rule
            else:
                # Match against base filename or full normalized relative path
                if fnmatch.fnmatch(base_name, pat) or fnmatch.fnmatch(lowered_path, pat):
                    return rule
                # Support pattern containing directory separator
                if "/" in pat and fnmatch.fnmatch(lowered_path, f"*{pat}*"):
                    return rule

        return None

    @staticmethod
    def normalize_path(path_str: str) -> str:
        """Normalize target path by resolving tildes, relative steps, and slash conventions."""
        cleaned = path_str.strip().replace("\\", "/")
        if cleaned.startswith("~"):
            cleaned = os.path.expanduser(cleaned).replace("\\", "/")
        return os.path.normpath(cleaned).replace("\\", "/")
