"""Concurrency tests for tokenizer service."""

from __future__ import annotations

import threading
import time

from myrm_agent_harness.toolkits.retriever.bm25 import get_tokenizer_service


def test_concurrent_lazy_init() -> None:
    tokenizer = get_tokenizer_service()
    results: list[tuple[int, list[str]]] = []
    errors: list[tuple[int, str]] = []

    def init_and_tokenize(thread_id: int) -> None:
        try:
            tokens = tokenizer.tokenize(f"running test {thread_id}")
            results.append((thread_id, tokens))
        except Exception as exc:
            errors.append((thread_id, str(exc)))

    threads = [threading.Thread(target=init_and_tokenize, args=(i,)) for i in range(100)]

    start = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - start

    assert not errors, f"thread failures: {errors}"
    assert len(results) == 100
    assert elapsed < 30.0

    for thread_id, tokens in results[:5]:
        assert "running" in tokens or "test" in tokens, f"thread {thread_id}: {tokens}"


def test_concurrent_tokenize() -> None:
    tokenizer = get_tokenizer_service()
    tokenizer.tokenize("warmup")

    results: list[tuple[int, int, list[str]]] = []
    errors: list[tuple[int, str]] = []

    def tokenize_task(thread_id: int) -> None:
        try:
            for i in range(100):
                tokens = tokenizer.tokenize(f"machine learning algorithm {thread_id}-{i}")
                results.append((thread_id, i, tokens))
        except Exception as exc:
            errors.append((thread_id, str(exc)))

    threads = [threading.Thread(target=tokenize_task, args=(i,)) for i in range(20)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"thread failures: {errors}"
    assert len(results) == 2000

    for thread_id, i, tokens in results[::100]:
        assert "machine" in tokens or "learning" in tokens or "algorithm" in tokens, (
            f"thread {thread_id}-{i}: {tokens}"
        )
