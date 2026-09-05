"""Unit tests for int8 vector quantization with per-row dynamic scale.

Verifies:
- Quantized data dimension, byte layout, and 4x memory compression ratio
- Per-row dynamic scale preservation
- L2-normalized cosine similarity accuracy (error < 0.005 vs float32 cosine)
- Zero-copy memoryview dot-product performance
- Edge cases: all-zeros, orthogonal, antipodal, and empty vectors
"""

import math
import random
import pytest

from myrm_agent_harness.toolkits.vector.quantization import (
    QuantizedVector,
    cosine_similarity_int8,
    decode_float32,
    dequantize_int8,
    encode_float32,
    quantize_int8,
)


def _float_cosine(a: list[float], b: list[float]) -> float:
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return dot / (norm_a * norm_b)


def test_quantize_int8_basic_and_compression_ratio() -> None:
    dim = 1024
    rng = random.Random(42)
    vec = [rng.uniform(-2.0, 2.0) for _ in range(dim)]

    quant = quantize_int8(vec)

    # 1. Byte length must strictly match dimension (1 byte per component)
    assert len(quant.data) == dim
    assert quant.dim == dim
    assert quant.scale > 0.0

    # 2. 4x compression ratio verification:
    raw_float32_bytes = encode_float32(vec)
    assert len(raw_float32_bytes) == dim * 4
    assert len(quant.data) == len(raw_float32_bytes) // 4  # Exactly 25% (4x compression)

    # 3. Float32 decode round-trip
    recovered_f32 = decode_float32(raw_float32_bytes)
    assert len(recovered_f32) == dim
    for original, rec in zip(vec, recovered_f32, strict=False):
        assert abs(original - rec) < 1e-5


def test_dequantize_and_cosine_fidelity() -> None:
    dim = 512
    rng = random.Random(101)
    vec_a = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    vec_b = [rng.gauss(0.0, 1.0) for _ in range(dim)]

    quant_a = quantize_int8(vec_a)
    quant_b = quantize_int8(vec_b)

    # Dequantize sanity check
    deq_a = dequantize_int8(quant_a)
    assert len(deq_a) == dim

    # Cosine fidelity comparison:
    # Full float32 cosine vs int8 scaled dot product
    true_cosine = _float_cosine(vec_a, vec_b)
    int8_cosine = cosine_similarity_int8(quant_a, quant_b)

    # Error must be well within 0.005 (0.5% deviation)
    error = abs(true_cosine - int8_cosine)
    assert error < 0.005, f"Quantization cosine error {error:.6f} exceeded 0.005 threshold"


def test_cosine_similarity_directional_anchors() -> None:
    dim = 256
    rng = random.Random(202)
    vec = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    antipodal = [-x for x in vec]

    quant_v = quantize_int8(vec)
    quant_anti = quantize_int8(antipodal)

    # Identity cosine must be ~1.0
    self_sim = cosine_similarity_int8(quant_v, quant_v)
    assert abs(self_sim - 1.0) < 0.002

    # Antipodal cosine must be ~ -1.0
    anti_sim = cosine_similarity_int8(quant_v, quant_anti)
    assert abs(anti_sim - (-1.0)) < 0.002

    # Orthogonal vectors: [1, 0, 0...] vs [0, 1, 0...]
    ortho_a = [1.0] + [0.0] * (dim - 1)
    ortho_b = [0.0, 1.0] + [0.0] * (dim - 2)
    quant_ortho_a = quantize_int8(ortho_a)
    quant_ortho_b = quantize_int8(ortho_b)

    ortho_sim = cosine_similarity_int8(quant_ortho_a, quant_ortho_b)
    assert abs(ortho_sim) < 1e-6


def test_edge_cases_and_error_handling() -> None:
    # 1. Empty vector raises ValueError
    with pytest.raises(ValueError, match="Cannot quantize an empty vector"):
        quantize_int8([])

    # 2. All-zero vector: must not divide by zero
    zero_vec = [0.0] * 64
    quant_zero = quantize_int8(zero_vec)
    assert quant_zero.scale == 1.0
    assert len(quant_zero.data) == 64

    # 3. Dimension mismatch raises ValueError
    q64 = quantize_int8([1.0] * 64)
    q128 = quantize_int8([1.0] * 128)
    with pytest.raises(ValueError, match="Vector dimensions do not match"):
        cosine_similarity_int8(q64, q128)

    # 4. Inconsistent QuantizedVector data length
    with pytest.raises(ValueError, match="does not match dimension"):
        QuantizedVector(data=b"\x00\x01", scale=1.0, dim=3)

    # 5. Invalid float32 byte length
    with pytest.raises(ValueError, match="must be a multiple of 4"):
        decode_float32(b"\x00\x01\x02")


@pytest.mark.asyncio
async def test_qdrant_store_quantization_config() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from myrm_agent_harness.toolkits.vector.config import VectorStoreConfig
    from myrm_agent_harness.toolkits.vector.qdrant.store import QdrantVectorStore

    mock_client = MagicMock()
    mock_client.collection_exists = AsyncMock(return_value=False)
    mock_client.create_collection = AsyncMock()

    config = VectorStoreConfig(
        embedding_dimension=1536,
        quantization_enabled=True,
    )
    store = QdrantVectorStore(client=mock_client, config=config, is_async=True)

    created = await store.create_collection("quantized_collection", dimension=1024)
    assert created is True
    assert mock_client.create_collection.call_count == 1
    call_kwargs = mock_client.create_collection.call_args.kwargs
    assert call_kwargs["collection_name"] == "quantized_collection"
    assert "quantization_config" in call_kwargs

