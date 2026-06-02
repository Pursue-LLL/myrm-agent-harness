"""并发测试：验证线程安全和竞态条件。"""

import threading
import time

import pytest

from myrm_agent_harness.toolkits.retriever.bm25 import get_tokenizer_service


def test_concurrent_lazy_init():
    """测试多线程并发初始化（验证 Double-check locking）。"""
    tokenizer = get_tokenizer_service()

    # 重置状态
    tokenizer._stemmer = None
    tokenizer._stopwords = None
    tokenizer._nltk_init_failed = False

    results = []
    errors = []

    def init_and_tokenize(thread_id: int):
        """每个线程执行分词（触发懒加载）"""
        try:
            tokens = tokenizer.tokenize(f"running test {thread_id}", enable_english_enhancement=True)
            results.append((thread_id, tokens))
        except Exception as e:
            errors.append((thread_id, str(e)))

    # 创建 100 个线程并发初始化
    threads = [threading.Thread(target=init_and_tokenize, args=(i,)) for i in range(100)]

    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start

    print(f"\n{'=' * 70}")
    print("并发初始化测试")
    print(f"{'=' * 70}")
    print(f"线程数: {len(threads)}")
    print(f"成功: {len(results)}")
    print(f"失败: {len(errors)}")
    print(f"总耗时: {elapsed:.3f}s")
    print(f"{'=' * 70}")

    # 断言
    assert len(errors) == 0, f"有线程失败: {errors}"
    assert len(results) == 100, f"应该有 100 个结果，实际: {len(results)}"

    # 验证所有线程都初始化成功（如果启用了英文增强）
    if not tokenizer._nltk_init_failed:
        assert tokenizer._stemmer is not None, "NLTK 应该初始化成功"
        assert tokenizer._stopwords is not None, "Stopwords 应该加载成功"

    # 验证分词结果正确
    for thread_id, tokens in results[:5]:  # 检查前 5 个
        assert "run" in tokens or "test" in tokens, f"线程 {thread_id} 分词结果异常: {tokens}"


def test_concurrent_tokenize():
    """测试多线程并发分词（验证无竞态条件）。"""
    tokenizer = get_tokenizer_service()

    # 预加载（避免懒加载影响测试）
    tokenizer.tokenize("warmup", enable_english_enhancement=True)

    results = []
    errors = []

    def tokenize_task(thread_id: int):
        """每个线程执行 100 次分词"""
        try:
            for i in range(100):
                tokens = tokenizer.tokenize(
                    f"machine learning algorithm {thread_id}-{i}",
                    enable_english_enhancement=True,
                )
                results.append((thread_id, i, tokens))
        except Exception as e:
            errors.append((thread_id, str(e)))

    # 创建 20 个线程并发分词
    threads = [threading.Thread(target=tokenize_task, args=(i,)) for i in range(20)]

    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start

    print(f"\n{'=' * 70}")
    print("并发分词测试")
    print(f"{'=' * 70}")
    print(f"线程数: {len(threads)}")
    print("每线程迭代: 100")
    print(f"总分词次数: {len(results)}")
    print(f"失败次数: {len(errors)}")
    print(f"总耗时: {elapsed:.3f}s")
    print(f"{'=' * 70}")

    # 断言
    assert len(errors) == 0, f"有线程失败: {errors}"
    assert len(results) == 2000, f"应该有 2000 个结果，实际: {len(results)}"

    # 验证分词结果正确性（抽样检查）
    for thread_id, i, tokens in results[::100]:  # 每 100 个检查一次
        assert "machin" in tokens or "learn" in tokens or "algorithm" in tokens, (
            f"线程 {thread_id}-{i} 分词结果异常: {tokens}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
