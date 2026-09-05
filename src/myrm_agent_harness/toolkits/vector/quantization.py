"""Int8 Vector Quantization with Per-Row Dynamic Scale & Zero-Allocation Dot Product.

[INPUT]
- collections.abc::Sequence (POS: Abstract sequence type for input vectors)
- math::sqrt (POS: Standard square root computation for L2 norm)

[OUTPUT]
- QuantizedVector: Immutable data model for int8 quantized vector with per-row scale
- quantize_int8: L2 normalization + per-row dynamic int8 quantization
- dequantize_int8: Reconstruct approximate float vector from int8 bytes and scale
- cosine_similarity_int8: Zero-copy dot-product cosine similarity between two quantized vectors
- encode_float32: Pack float sequence into compact 32-bit little-endian bytes
- decode_float32: Unpack 32-bit little-endian bytes into float list

[POS]
Harness vector quantization toolkit. Provides high-performance, model-free int8
vector compression (4x memory reduction) and zero-copy dot product similarity
calculation for desktop, local, and sandbox embedded memory environments.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass

INT8_MAX: int = 127


@dataclass(frozen=True, slots=True)
class QuantizedVector:
    """Immutable representation of a per-row dynamically scaled int8 vector."""

    data: bytes
    scale: float
    dim: int

    def __post_init__(self) -> None:
        if len(self.data) != self.dim:
            raise ValueError(
                f"QuantizedVector data byte length ({len(self.data)}) does not match dimension ({self.dim})"
            )


def quantize_int8(vector: Sequence[float]) -> QuantizedVector:
    """Perform L2-normalization and per-row dynamic int8 quantization.

    Each row is independently scaled using its own max absolute value after
    L2 normalization (scale = max_abs / 127.0). This utilizes the full ±127
    dynamic range of signed 8-bit integers without global scale dilution.

    Args:
        vector: Input float vector (e.g. 1024 or 2048 dimensions).

    Returns:
        QuantizedVector with int8 bytes, dynamic scale factor, and dimension.

    Raises:
        ValueError: If vector is empty.
    """
    dim = len(vector)
    if dim == 0:
        raise ValueError("Cannot quantize an empty vector")

    sum_sq = sum(v * v for v in vector)
    norm = math.sqrt(sum_sq)
    inv_norm = 1.0 / norm if norm > 0.0 else 0.0

    normalized: list[float] = [v * inv_norm for v in vector]
    max_abs = max(abs(v) for v in normalized) if normalized else 0.0

    scale = max_abs / INT8_MAX if max_abs > 0.0 else 1.0
    inv_scale = 1.0 / scale

    # Clamp to [-127, 127] to maintain symmetric dynamic range without -128 overflow
    quantized_ints = [
        max(-INT8_MAX, min(INT8_MAX, round(v * inv_scale)))
        for v in normalized
    ]

    data = struct.pack(f"{dim}b", *quantized_ints)
    return QuantizedVector(data=data, scale=scale, dim=dim)


def dequantize_int8(quantized: QuantizedVector) -> list[float]:
    """Reconstruct an approximate float vector from int8 bytes and per-row scale.

    Args:
        quantized: The QuantizedVector instance.

    Returns:
        List of reconstructed float values.
    """
    view = memoryview(quantized.data).cast("b")
    scale = quantized.scale
    return [int(val) * scale for val in view]


def cosine_similarity_int8(a: QuantizedVector, b: QuantizedVector) -> float:
    """Calculate cosine similarity between two int8 quantized vectors.

    Because both vectors are pre-L2 normalized during quantization, cosine
    similarity is equivalent to the scaled dot product: dot(a, b) * scaleA * scaleB.
    Zero-copy memoryview casting is used to avoid garbage collection pressure.

    Args:
        a: First quantized vector.
        b: Second quantized vector.

    Returns:
        Cosine similarity score in range [-1.0, 1.0].

    Raises:
        ValueError: If dimensions do not match.
    """
    if a.dim != b.dim:
        raise ValueError(f"Vector dimensions do not match: {a.dim} != {b.dim}")

    view_a = memoryview(a.data).cast("b")
    view_b = memoryview(b.data).cast("b")

    dot: int = 0
    for idx in range(a.dim):
        dot += view_a[idx] * view_b[idx]

    raw_cosine = dot * a.scale * b.scale
    return max(-1.0, min(1.0, raw_cosine))


def encode_float32(vector: Sequence[float]) -> bytes:
    """Pack a float sequence into raw 32-bit little-endian IEEE-754 bytes.

    Args:
        vector: Sequence of floating-point numbers.

    Returns:
        Compact byte sequence of length len(vector) * 4.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


def decode_float32(data: bytes) -> list[float]:
    """Unpack raw 32-bit little-endian bytes into a list of floats.

    Args:
        data: Byte sequence whose length is a multiple of 4.

    Returns:
        List of decoded floats.

    Raises:
        ValueError: If data byte length is not a multiple of 4.
    """
    if len(data) % 4 != 0:
        raise ValueError(f"Data length ({len(data)}) must be a multiple of 4 for float32 decoding")
    count = len(data) // 4
    return list(struct.unpack(f"<{count}f", data))
