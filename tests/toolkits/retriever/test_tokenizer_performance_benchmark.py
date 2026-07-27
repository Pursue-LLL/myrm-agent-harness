"""真实业务场景的分词性能基准测试。"""

import time

import pytest

from myrm_agent_harness.toolkits.retriever.bm25_retrieval import BM25Retriever


@pytest.fixture
def large_document_corpus():
    """生成大规模文档语料（模拟真实知识库）。"""
    documents = []

    tech_docs = [
        "Python is a high-level programming language widely used for data science and machine learning applications",
        "Deep learning models are trained using neural networks with multiple layers and backpropagation algorithms",
        "FastAPI is a modern web framework for building APIs with Python based on standard Python type hints",
        "Docker containers provide lightweight virtualization for application deployment and microservices architecture",
        "Kubernetes orchestrates containerized applications across distributed computing clusters efficiently",
        "TensorFlow and PyTorch are popular deep learning frameworks for building neural network models",
        "React is a JavaScript library for building user interfaces with component-based architecture",
        "PostgreSQL is a powerful open-source relational database management system supporting advanced features",
        "Redis provides in-memory data structure storage for caching and real-time applications",
        "Elasticsearch enables full-text search and analytics for large-scale data processing",
    ]

    chinese_docs = [
        "机器学习是人工智能的核心技术，通过算法让计算机从数据中学习",
        "深度学习使用多层神经网络进行特征提取和模式识别",
        "自然语言处理技术应用于文本分类、情感分析和机器翻译",
        "大语言模型通过海量文本数据预训练获得强大的语言理解能力",
        "向量数据库用于高效存储和检索高维向量数据",
        "检索增强生成技术结合检索和生成提升模型输出质量",
        "提示工程是优化大语言模型输出的关键技术",
        "知识图谱通过结构化表示实体和关系增强推理能力",
        "多模态模型可以处理文本、图像、音频等多种数据类型",
        "强化学习通过奖励信号训练智能体进行决策优化",
    ]

    mixed_docs = [
        "使用 Python 的 scikit-learn 库可以快速实现机器学习算法",
        "TensorFlow 2.0 引入了 Eager Execution 简化了模型开发流程",
        "Docker 容器技术大幅提升了应用部署的效率和可靠性",
        "Kubernetes 集群管理系统支持自动扩缩容和服务发现",
        "React Hooks 提供了更简洁的状态管理和副作用处理方式",
    ]

    for _ in range(40):
        documents.extend(tech_docs)
        documents.extend(chinese_docs)
        documents.extend(mixed_docs)

    return documents


@pytest.fixture
def test_queries():
    """生成测试查询集合。"""
    return [
        "Python machine learning",
        "deep learning neural networks",
        "FastAPI web framework",
        "Docker container deployment",
        "Kubernetes cluster management",
        "TensorFlow PyTorch comparison",
        "React component architecture",
        "PostgreSQL database features",
        "Redis caching strategies",
        "Elasticsearch search analytics",
        "机器学习算法",
        "深度学习神经网络",
        "自然语言处理",
        "大语言模型",
        "向量数据库检索",
        "检索增强生成",
        "提示工程技术",
        "知识图谱推理",
        "多模态模型",
        "强化学习优化",
        "Python 机器学习",
        "TensorFlow 深度学习",
        "Docker 容器部署",
        "Kubernetes 集群",
        "React 前端开发",
    ]


def test_bm25_retrieval_performance(large_document_corpus, test_queries):
    """测试 BM25 检索在真实语料上的性能。"""
    index_start = time.perf_counter()
    retriever = BM25Retriever(large_document_corpus)
    index_time = time.perf_counter() - index_start

    query_start = time.perf_counter()
    for query in test_queries:
        retriever.search(query, top_k=10)
    query_time = time.perf_counter() - query_start

    total_time = index_time + query_time

    print(f"\n{'=' * 70}")
    print("BM25 检索性能")
    print(f"{'=' * 70}")
    print(f"文档数量: {len(large_document_corpus)}")
    print(f"查询数量: {len(test_queries)}")
    print(f"索引构建: {index_time:.3f}s")
    print(f"查询执行: {query_time:.3f}s ({query_time / len(test_queries) * 1000:.2f}ms/query)")
    print(f"总耗时:   {total_time:.3f}s")

    assert index_time < 5.0, "索引构建不应超过 5 秒"
    assert query_time / len(test_queries) < 0.1, "单次查询不应超过 100ms"


def test_tokenizer_stats(large_document_corpus) -> None:
    """测试分词器功能验证。"""
    from myrm_agent_harness.toolkits.retriever.bm25 import get_tokenizer_service

    tokenizer = get_tokenizer_service()

    token_counts = []
    for doc in large_document_corpus[:100]:
        tokens = tokenizer.tokenize(doc)
        token_counts.append(len(tokens))

    print(f"\n{'=' * 70}")
    print("分词器功能验证")
    print(f"{'=' * 70}")
    print(f"平均 tokens: {sum(token_counts) / len(token_counts):.1f}")
    print(f"{'=' * 70}")

    assert all(count > 0 for count in token_counts), "分词应该有结果"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
