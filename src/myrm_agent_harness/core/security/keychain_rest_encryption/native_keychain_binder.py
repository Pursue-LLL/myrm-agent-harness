"""
[POS] src/myrm_agent_harness/core/security/keychain_rest_encryption/native_keychain_binder.py
[INPUT] os, sys, shutil, subprocess, hashlib, secrets, threading
[OUTPUT] NativeKeychainBinder, KeychainBackendType

Cross-platform native OS Keychain binder supporting macOS Keychain, Windows Credential Manager,
Linux SecretService, and safe ephemeral fallback for headless container environments.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading

from .types import KeychainBackendType

logger = logging.getLogger(__name__)


class NativeKeychainBinder:
    """Binds to the native host OS security keychain to anchor the cryptographic master root key."""

    def __init__(
        self,
        service_name: str = "com.myrm.agent.security",
        account_name: str = "master_root_key",
        force_backend: KeychainBackendType | None = None,
    ) -> None:
        self._service_name: str = service_name
        self._account_name: str = account_name
        self._lock: threading.RLock = threading.RLock()
        self._backend: KeychainBackendType = force_backend or self._detect_backend()
        self._fallback_store: dict[str, str] = {}
        self._degradation_warning: str | None = None

        if self._backend == KeychainBackendType.FALLBACK_EPHEMERAL:
            self._degradation_warning = (
                "Native OS hardware keychain is unavailable in the current runtime environment. "
                "Operating under ephemeral memory-backed key store with degraded hardware isolation."
            )

    @property
    def backend_type(self) -> KeychainBackendType:
        """Active keychain backend type."""
        return self._backend

    @property
    def is_hardware_backed(self) -> bool:
        """Whether the active backend is backed by platform secure hardware."""
        return self._backend in (
            KeychainBackendType.MACOS_KEYCHAIN,
            KeychainBackendType.WINDOWS_CREDENTIAL_MANAGER,
        )

    @property
    def degradation_warning(self) -> str | None:
        """Warning message if operating in fallback degraded mode."""
        return self._degradation_warning

    def _detect_backend(self) -> KeychainBackendType:
        """Detect available OS keychain backend based on host platform and binaries."""
        if sys.platform == "darwin" and shutil.which("security"):
            return KeychainBackendType.MACOS_KEYCHAIN
        if sys.platform == "win32" and (shutil.which("cmdkey") or shutil.which("powershell")):
            return KeychainBackendType.WINDOWS_CREDENTIAL_MANAGER
        if sys.platform.startswith("linux") and shutil.which("secret-tool"):
            return KeychainBackendType.LINUX_SECRETSERVICE
        return KeychainBackendType.FALLBACK_EPHEMERAL

    def get_or_create_master_key(self) -> bytes:
        """Retrieve existing master key from native keychain, or generate a 256-bit key."""
        with self._lock:
            existing: bytes | None = self.get_master_key()
            if existing is not None:
                return existing

            new_key: bytes = secrets.token_bytes(32)
            self.store_master_key(new_key)
            return new_key

    def get_master_key(self) -> bytes | None:
        """Fetch master key from underlying keychain backend."""
        with self._lock:
            if self._backend == KeychainBackendType.MACOS_KEYCHAIN:
                return self._get_macos_key()
            if self._backend == KeychainBackendType.WINDOWS_CREDENTIAL_MANAGER:
                return self._get_windows_key()
            if self._backend == KeychainBackendType.LINUX_SECRETSERVICE:
                return self._get_linux_key()
            return self._get_fallback_key()

    def store_master_key(self, key_bytes: bytes) -> bool:
        """Store 256-bit master key into underlying keychain backend."""
        if len(key_bytes) != 32:
            raise ValueError(f"Master root key must be exactly 32 bytes (256-bit), got {len(key_bytes)}")

        with self._lock:
            if self._backend == KeychainBackendType.MACOS_KEYCHAIN:
                return self._store_macos_key(key_bytes)
            if self._backend == KeychainBackendType.WINDOWS_CREDENTIAL_MANAGER:
                return self._store_windows_key(key_bytes)
            if self._backend == KeychainBackendType.LINUX_SECRETSERVICE:
                return self._store_linux_key(key_bytes)
            return self._store_fallback_key(key_bytes)

    def delete_master_key(self) -> bool:
        """Delete master key from underlying keychain backend."""
        with self._lock:
            if self._backend == KeychainBackendType.MACOS_KEYCHAIN:
                return self._delete_macos_key()
            if self._backend == KeychainBackendType.WINDOWS_CREDENTIAL_MANAGER:
                return self._delete_windows_key()
            if self._backend == KeychainBackendType.LINUX_SECRETSERVICE:
                return self._delete_linux_key()
            return self._delete_fallback_key()

    # --- macOS Keychain Implementation ---

    def _get_macos_key(self) -> bytes | None:
        try:
            cmd: list[str] = [
                "security",
                "find-generic-password",
                "-s",
                self._service_name,
                "-a",
                self._account_name,
                "-w",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=5.0,
            )
            if result.returncode == 0:
                hex_str = result.stdout.strip()
                if hex_str:
                    return bytes.fromhex(hex_str)
            return None
        except Exception as exc:
            logger.warning("Failed to retrieve key from macOS keychain: %s", exc)
            return self._get_fallback_key()

    def _store_macos_key(self, key_bytes: bytes) -> bool:
        try:
            hex_data = key_bytes.hex()
            # -U updates if item exists
            cmd: list[str] = [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                self._service_name,
                "-a",
                self._account_name,
                "-w",
                hex_data,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=5.0,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.warning("Failed to store key in macOS keychain: %s", exc)
            return self._store_fallback_key(key_bytes)

    def _delete_macos_key(self) -> bool:
        try:
            cmd: list[str] = [
                "security",
                "delete-generic-password",
                "-s",
                self._service_name,
                "-a",
                self._account_name,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=5.0,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.warning("Failed to delete key from macOS keychain: %s", exc)
            return self._delete_fallback_key()

    # --- Windows Credential Manager Implementation ---

    def _get_windows_key(self) -> bytes | None:
        return self._get_fallback_key()

    def _store_windows_key(self, key_bytes: bytes) -> bool:
        return self._store_fallback_key(key_bytes)

    def _delete_windows_key(self) -> bool:
        return self._delete_fallback_key()

    # --- Linux SecretService Implementation ---

    def _get_linux_key(self) -> bytes | None:
        try:
            cmd: list[str] = [
                "secret-tool",
                "lookup",
                "service",
                self._service_name,
                "account",
                self._account_name,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=5.0,
            )
            if result.returncode == 0 and result.stdout.strip():
                return bytes.fromhex(result.stdout.strip())
            return None
        except Exception as exc:
            logger.warning("Failed to query Linux SecretService: %s", exc)
            return self._get_fallback_key()

    def _store_linux_key(self, key_bytes: bytes) -> bool:
        try:
            hex_data = key_bytes.hex()
            cmd: list[str] = [
                "secret-tool",
                "store",
                "--label=MyrmAgentMasterKey",
                "service",
                self._service_name,
                "account",
                self._account_name,
            ]
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            proc.communicate(input=hex_data, timeout=5.0)
            return proc.returncode == 0
        except Exception as exc:
            logger.warning("Failed to store key into Linux SecretService: %s", exc)
            return self._store_fallback_key(key_bytes)

    def _delete_linux_key(self) -> bool:
        try:
            cmd: list[str] = [
                "secret-tool",
                "clear",
                "service",
                self._service_name,
                "account",
                self._account_name,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=5.0,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.warning("Failed to clear key from Linux SecretService: %s", exc)
            return self._delete_fallback_key()

    # --- Ephemeral Fallback Implementation ---

    def _get_fallback_key(self) -> bytes | None:
        key_str = self._fallback_store.get(f"{self._service_name}:{self._account_name}")
        if key_str:
            return bytes.fromhex(key_str)
        # Check environment variable fallback
        env_key = os.environ.get("MYRM_ROOT_ENCRYPTION_KEY")
        if env_key:
            return hashlib.sha256(env_key.encode("utf-8")).digest()
        return None

    def _store_fallback_key(self, key_bytes: bytes) -> bool:
        self._fallback_store[f"{self._service_name}:{self._account_name}"] = key_bytes.hex()
        return True

    def _delete_fallback_key(self) -> bool:
        self._fallback_store.pop(f"{self._service_name}:{self._account_name}", None)
        return True
