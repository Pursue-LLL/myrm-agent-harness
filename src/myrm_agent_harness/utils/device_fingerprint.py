"""Device fingerprint generation for encryption key derivation.

Generates a stable device identifier based on hardware characteristics.
Framework-layer utility with no business logic.

[INPUT]

[OUTPUT]
- get_device_fingerprint(): str (stable device identifier)
- generate_recovery_key(): str (user-friendly recovery key)

[POS]
Pure utility for device identification. Used by business layer to derive
encryption keys for local storage. No user_id, no deployment mode checks.

Design principles:
- Cross-platform compatible (macOS, Linux, Windows)
- Stable across reboots
- Changes only when hardware changes
- No network access
- No user-specific data
"""

from __future__ import annotations

import base64
import hashlib
import logging
import platform
import secrets
import subprocess
import uuid
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_device_fingerprint() -> str:
    """Get stable device fingerprint based on hardware characteristics.

    Returns a SHA-256 hash of hardware identifiers (machine ID, MAC address, etc.).
    This fingerprint is stable across reboots but changes if hardware changes.

    Returns:
        64-character hexadecimal string (SHA-256 hash)

    Note:
        - macOS: Uses IOPlatformUUID
        - Linux: Uses /etc/machine-id or /var/lib/dbus/machine-id
        - Windows: Uses MachineGuid from registry
        - Fallback: Uses MAC address + hostname
    """
    try:
        system = platform.system()

        if system == "Darwin":  # macOS
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "IOPlatformUUID" in line:
                    machine_id = line.split('"')[3]
                    return hashlib.sha256(machine_id.encode()).hexdigest()

        elif system == "Linux":
            # Try /etc/machine-id first (systemd)
            try:
                with open("/etc/machine-id", encoding="utf-8") as f:
                    machine_id = f.read().strip()
                    return hashlib.sha256(machine_id.encode()).hexdigest()
            except FileNotFoundError:
                pass

            # Fallback to /var/lib/dbus/machine-id
            try:
                with open("/var/lib/dbus/machine-id", encoding="utf-8") as f:
                    machine_id = f.read().strip()
                    return hashlib.sha256(machine_id.encode()).hexdigest()
            except FileNotFoundError:
                pass

        elif system == "Windows":
            result = subprocess.run(
                ["reg", "query", "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography", "/v", "MachineGuid"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "MachineGuid" in line:
                    machine_id = line.split()[-1].strip()
                    return hashlib.sha256(machine_id.encode()).hexdigest()

    except Exception as e:
        logger.warning(f"Failed to get hardware machine ID: {e}, falling back to MAC+hostname")

    mac_address = format(uuid.getnode(), "x")
    hostname = platform.node()
    fallback_id = f"{mac_address}_{hostname}"
    return hashlib.sha256(fallback_id.encode()).hexdigest()


def generate_recovery_key() -> str:
    """Generate a random recovery key for backup purposes.

    Returns a 32-character base32-encoded key (160 bits of entropy).
    Users can export and save this key to recover encrypted data if
    hardware changes or system is reinstalled.

    Returns:
        32-character recovery key (format: XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX)

    Example:
        ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ23-4567
    """
    random_bytes = secrets.token_bytes(20)  # 160 bits
    base32 = base64.b32encode(random_bytes).decode("ascii")
    formatted = "-".join([base32[i : i + 4] for i in range(0, 32, 4)])
    return formatted


def derive_key_from_fingerprint(fingerprint: str, salt: str = "myrm-local-encryption-v1") -> bytes:
    """Derive 256-bit encryption key from device fingerprint.

    Args:
        fingerprint: Device fingerprint (from get_device_fingerprint())
        salt: Salt string for key derivation (default: 'myrm-local-encryption-v1')

    Returns:
        32-byte (256-bit) encryption key suitable for AES-256

    Note:
        Uses SHA-256 for key derivation (sufficient for device-based encryption).
        For user passwords, use PBKDF2 or Argon2 instead.
    """
    combined = f"{fingerprint}:{salt}"
    return hashlib.sha256(combined.encode()).digest()
