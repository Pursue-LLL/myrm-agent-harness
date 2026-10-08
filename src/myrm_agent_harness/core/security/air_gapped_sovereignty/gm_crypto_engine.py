"""
[POS] src/myrm_agent_harness/core/security/air_gapped_sovereignty/gm_crypto_engine.py
[INPUT] struct, typing
[OUTPUT] sm3_hash, sm4_encrypt_ecb, sm4_decrypt_ecb, SM3Hasher, SM4Cipher

Pure Python native implementation of Chinese National Commercial Cryptography (GM/T) algorithms:
- SM3 Cryptographic Hash Algorithm (GM/T 0004-2012, 256-bit digest)
- SM4 Block Cipher Algorithm (GM/T 0002-2012, 128-bit block / 128-bit key)

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import struct

# ==============================================================================
# SM3 Cryptographic Hash Algorithm (GM/T 0004-2012)
# ==============================================================================

_SM3_IV: tuple[int, ...] = (
    0x7380166F,
    0x4914B2B9,
    0x172442D7,
    0xDA8A0600,
    0xA96F30BC,
    0x163138AA,
    0xE38DEE4D,
    0xB0FB0E4E,
)


def _rotl(x: int, n: int) -> int:
    n %= 32
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _p0(x: int) -> int:
    return x ^ _rotl(x, 9) ^ _rotl(x, 17)


def _p1(x: int) -> int:
    return x ^ _rotl(x, 15) ^ _rotl(x, 23)


def _ff(x: int, y: int, z: int, j: int) -> int:
    if j < 16:
        return x ^ y ^ z
    return (x & y) | (x & z) | (y & z)


def _gg(x: int, y: int, z: int, j: int) -> int:
    if j < 16:
        return x ^ y ^ z
    return (x & y) | ((~x) & z)


class SM3Hasher:
    """SM3 cryptographic hash implementation."""

    @classmethod
    def hash(cls, data: bytes | str) -> str:
        """Compute SM3 256-bit hash hex digest."""
        msg = data.encode("utf-8") if isinstance(data, str) else data
        msg_len = len(msg)

        # Padding
        padded = bytearray(msg)
        padded.append(0x80)
        while (len(padded) % 64) != 56:
            padded.append(0x00)
        padded.extend(struct.pack(">Q", msg_len * 8))

        # Iterative compression
        v = list(_SM3_IV)
        for i in range(0, len(padded), 64):
            block = padded[i : i + 64]
            v = cls._compress(v, block)

        return "".join(f"{x:08x}" for x in v)

    @classmethod
    def _compress(cls, v: list[int], b: bytearray | bytes) -> list[int]:
        w = list(struct.unpack(">16I", b))
        for j in range(16, 68):
            tmp = _p1(w[j - 16] ^ w[j - 9] ^ _rotl(w[j - 3], 15)) ^ _rotl(w[j - 13], 7) ^ w[j - 6]
            w.append(tmp & 0xFFFFFFFF)

        w1 = [w[j] ^ w[j + 4] for j in range(64)]

        a, b_reg, c, d, e, f, g, h = v

        for j in range(64):
            t_j = 0x79CC4519 if j < 16 else 0x7A879D8A
            ss1 = _rotl((_rotl(a, 12) + e + _rotl(t_j, j % 32)) & 0xFFFFFFFF, 7)
            ss2 = ss1 ^ _rotl(a, 12)
            tt1 = (_ff(a, b_reg, c, j) + d + ss2 + w1[j]) & 0xFFFFFFFF
            tt2 = (_gg(e, f, g, j) + h + ss1 + w[j]) & 0xFFFFFFFF
            d = c
            c = _rotl(b_reg, 9)
            b_reg = a
            a = tt1
            h = g
            g = _rotl(f, 19)
            f = e
            e = _p0(tt2)

        return [
            (v[0] ^ a) & 0xFFFFFFFF,
            (v[1] ^ b_reg) & 0xFFFFFFFF,
            (v[2] ^ c) & 0xFFFFFFFF,
            (v[3] ^ d) & 0xFFFFFFFF,
            (v[4] ^ e) & 0xFFFFFFFF,
            (v[5] ^ f) & 0xFFFFFFFF,
            (v[6] ^ g) & 0xFFFFFFFF,
            (v[7] ^ h) & 0xFFFFFFFF,
        ]


def sm3_hash(data: bytes | str) -> str:
    """Convenience helper to compute SM3 digest."""
    return SM3Hasher.hash(data)


# ==============================================================================
# SM4 Block Cipher Algorithm (GM/T 0002-2012)
# ==============================================================================

_SM4_SBOX: tuple[int, ...] = (
    0xd6, 0x90, 0xe9, 0xfe, 0xcc, 0xe1, 0x3d, 0xb7, 0x16, 0xb6, 0x14, 0xc2, 0x28, 0xfb, 0x2c, 0x05,
    0x2b, 0x67, 0x9a, 0x76, 0x2a, 0xbe, 0x04, 0xc3, 0xaa, 0x44, 0x13, 0x26, 0x49, 0x86, 0x06, 0x99,
    0x9c, 0x42, 0x50, 0xf4, 0x91, 0xef, 0x98, 0x7a, 0x33, 0x54, 0x0b, 0x43, 0xed, 0xcf, 0xac, 0x62,
    0xe4, 0xb3, 0x1c, 0xa9, 0xc9, 0x08, 0xe8, 0x95, 0x80, 0xdf, 0x94, 0xfa, 0x75, 0x8f, 0x3f, 0xa6,
    0x47, 0x07, 0xa7, 0xfc, 0xf3, 0x73, 0x17, 0xba, 0x83, 0x59, 0x3c, 0x19, 0xe6, 0x85, 0x4f, 0xa8,
    0x68, 0x6b, 0x81, 0xb2, 0x71, 0x64, 0xda, 0x8b, 0xf8, 0xeb, 0x0f, 0x4b, 0x70, 0x56, 0x9d, 0x35,
    0x1e, 0x24, 0x0e, 0x5e, 0x63, 0x58, 0xd1, 0xa2, 0x25, 0x22, 0x7c, 0x3b, 0x01, 0x21, 0x78, 0x87,
    0xd4, 0x00, 0x46, 0x57, 0x9f, 0xd3, 0x27, 0x52, 0x4c, 0x36, 0x02, 0xe7, 0xa0, 0xc4, 0xc8, 0x9e,
    0xea, 0xbf, 0x8a, 0xd2, 0x40, 0xc7, 0x38, 0xb5, 0xa3, 0xf7, 0xf2, 0xce, 0xf9, 0x61, 0x15, 0xa1,
    0xe0, 0xae, 0x5d, 0xa4, 0x9b, 0x34, 0x1a, 0x55, 0xad, 0x93, 0x32, 0x30, 0xf5, 0x8c, 0xb1, 0xe3,
    0x1d, 0xf6, 0xe2, 0x2e, 0x82, 0x66, 0xca, 0x60, 0xc0, 0x29, 0x23, 0xab, 0x0d, 0x53, 0x4e, 0x6f,
    0xd5, 0xdb, 0x37, 0x45, 0xde, 0xfd, 0x8e, 0x2f, 0x03, 0xff, 0x6a, 0x72, 0x6d, 0x6c, 0x5b, 0x51,
    0x8d, 0x1b, 0xaf, 0x92, 0xbb, 0xdd, 0xbc, 0x7f, 0x11, 0xd9, 0x5c, 0x41, 0x1f, 0x10, 0x5a, 0xd8,
    0x0a, 0xc1, 0x31, 0x88, 0xa5, 0xcd, 0x7b, 0xbd, 0x2d, 0x74, 0xd0, 0x12, 0xb8, 0xe5, 0xb4, 0xb0,
    0x89, 0x69, 0x97, 0x4a, 0x0c, 0x96, 0x77, 0x7e, 0x65, 0xb9, 0xf1, 0x09, 0xc5, 0x6e, 0xc6, 0x84,
    0x18, 0xf0, 0x7d, 0xec, 0x3a, 0xdc, 0x4d, 0x20, 0x79, 0xee, 0x5f, 0x3e, 0xd7, 0xcb, 0x39, 0x48,
)

_SM4_FK: tuple[int, ...] = (0xA3B1BAC6, 0x56AA3350, 0x677D9197, 0xB27022DC)

_SM4_CK: tuple[int, ...] = tuple(
    (
        ((((4 * i) * 7) % 256) << 24)
        | ((((4 * i + 1) * 7) % 256) << 16)
        | ((((4 * i + 2) * 7) % 256) << 8)
        | (((4 * i + 3) * 7) % 256)
    )
    for i in range(32)
)


def _sm4_tau(a: int) -> int:
    b0 = _SM4_SBOX[(a >> 24) & 0xFF]
    b1 = _SM4_SBOX[(a >> 16) & 0xFF]
    b2 = _SM4_SBOX[(a >> 8) & 0xFF]
    b3 = _SM4_SBOX[a & 0xFF]
    return (b0 << 24) | (b1 << 16) | (b2 << 8) | b3


def _sm4_l(b: int) -> int:
    return b ^ _rotl(b, 2) ^ _rotl(b, 10) ^ _rotl(b, 18) ^ _rotl(b, 24)


def _sm4_l_prime(b: int) -> int:
    return b ^ _rotl(b, 13) ^ _rotl(b, 23)


class SM4Cipher:
    """SM4 128-bit symmetric block cipher implementation."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 16:
            raise ValueError("SM4 requires exactly a 16-byte (128-bit) key.")
        self._round_keys = self._key_expansion(key)

    @staticmethod
    def _key_expansion(key: bytes) -> list[int]:
        mk = list(struct.unpack(">4I", key))
        k = [mk[i] ^ _SM4_FK[i] for i in range(4)]
        rk: list[int] = []
        for i in range(32):
            tmp = k[i + 1] ^ k[i + 2] ^ k[i + 3] ^ _SM4_CK[i]
            ki = k[i] ^ _sm4_l_prime(_sm4_tau(tmp))
            k.append(ki & 0xFFFFFFFF)
            rk.append(ki & 0xFFFFFFFF)
        return rk

    def encrypt_block(self, block: bytes) -> bytes:
        """Encrypt single 16-byte block."""
        return self._process_block(block, self._round_keys)

    def decrypt_block(self, block: bytes) -> bytes:
        """Decrypt single 16-byte block."""
        return self._process_block(block, list(reversed(self._round_keys)))

    @staticmethod
    def _process_block(block: bytes, rk: list[int]) -> bytes:
        if len(block) != 16:
            raise ValueError("SM4 block size must be exactly 16 bytes.")
        x = list(struct.unpack(">4I", block))
        for i in range(32):
            tmp = x[i + 1] ^ x[i + 2] ^ x[i + 3] ^ rk[i]
            xi = x[i] ^ _sm4_l(_sm4_tau(tmp))
            x.append(xi & 0xFFFFFFFF)
        return struct.pack(">4I", x[35], x[34], x[33], x[32])

    def encrypt_ecb(self, plaintext: bytes) -> bytes:
        """Encrypt byte sequence in ECB mode with PKCS#7 padding."""
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)
        ciphertext = bytearray()
        for i in range(0, len(padded), 16):
            ciphertext.extend(self.encrypt_block(padded[i : i + 16]))
        return bytes(ciphertext)

    def decrypt_ecb(self, ciphertext: bytes) -> bytes:
        """Decrypt byte sequence in ECB mode and strip PKCS#7 padding."""
        if len(ciphertext) == 0 or (len(ciphertext) % 16) != 0:
            raise ValueError("Ciphertext length must be a non-zero multiple of 16.")
        decrypted = bytearray()
        for i in range(0, len(ciphertext), 16):
            decrypted.extend(self.decrypt_block(ciphertext[i : i + 16]))
        pad_len = decrypted[-1]
        if pad_len < 1 or pad_len > 16:
            raise ValueError("Invalid PKCS#7 padding byte.")
        return bytes(decrypted[:-pad_len])


def sm4_encrypt_ecb(key: bytes, plaintext: bytes) -> bytes:
    """Convenience helper to encrypt with SM4-ECB."""
    return SM4Cipher(key).encrypt_ecb(plaintext)


def sm4_decrypt_ecb(key: bytes, ciphertext: bytes) -> bytes:
    """Convenience helper to decrypt with SM4-ECB."""
    return SM4Cipher(key).decrypt_ecb(ciphertext)
