"""Config encryption utilities.

Provides AES-256-GCM encryption for sensitive config values. Framework layer
provides pure encryption tools; business layer decides encryption policy.

Example:
    >>> from myrm_agent_harness.utils.crypto import ConfigCrypto
    >>> key = ConfigCrypto.derive_key("my-secret")
    >>> ciphertext = ConfigCrypto.encrypt_value({"api_key": "..."}, key)
    >>> plaintext = ConfigCrypto.decrypt_value(ciphertext, key)
"""

from .config_crypto import ConfigCrypto
from .exceptions import ConfigCryptoError, DecryptionError, EncryptionError

__all__ = [
    "ConfigCrypto",
    "ConfigCryptoError",
    "DecryptionError",
    "EncryptionError",
]
