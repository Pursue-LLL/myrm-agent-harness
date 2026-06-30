"""测试增强分词功能。

验证中英文混合分词、词干提取、停用词过滤等功能。
"""

import pytest

from myrm_agent_harness.toolkits.retriever.bm25.tokenizer import _ENGLISH_WORD_PATTERN, get_tokenizer_service

try:
    from nltk.stem import PorterStemmer
    _HAS_NLTK = True
except ImportError:
    _HAS_NLTK = False

requires_nltk = pytest.mark.skipif(not _HAS_NLTK, reason="NLTK not installed")


@pytest.fixture
def tokenizer():
    """获取分词器实例"""
    return get_tokenizer_service()


def test_english_word_detection():
    """测试英文词检测正则表达式"""
    assert _ENGLISH_WORD_PATTERN.match("hello")
    assert _ENGLISH_WORD_PATTERN.match("machine-learning")
    assert _ENGLISH_WORD_PATTERN.match("don't")
    assert not _ENGLISH_WORD_PATTERN.match("你好")
    assert not _ENGLISH_WORD_PATTERN.match("123")
    assert not _ENGLISH_WORD_PATTERN.match("hello123")


@requires_nltk
def test_simple_english_tokenization(tokenizer):
    """测试纯英文分词（需要 NLTK 停用词过滤和词干提取）"""
    text = "The quick brown fox jumps over the lazy dog"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    lower_tokens = [t.lower() for t in tokens]
    assert "the" not in lower_tokens
    assert "over" not in lower_tokens
    assert "jump" in tokens or "jump" in lower_tokens


def test_chinese_tokenization(tokenizer):
    """测试纯中文分词"""
    text = "机器学习是人工智能的重要分支"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    # 中文应正常分词
    assert "机器学习" in tokens or "机器" in tokens
    assert "人工智能" in tokens or "人工" in tokens

    print(f" 中文分词结果: {tokens}")


@requires_nltk
def test_mixed_language_tokenization(tokenizer):
    """测试中英文混合分词（需要 NLTK）"""
    text = "Python is a powerful programming language for 机器学习"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    # 英文部分：停用词过滤 + 词干提取
    assert "is" not in tokens  # 停用词
    assert "a" not in tokens  # 停用词
    assert "for" not in tokens  # 停用词
    assert "python" in tokens  # 转小写
    assert "program" in tokens  # programming → program

    # 中文部分：正常分词
    assert "机器学习" in tokens or "机器" in tokens

    print(f" 混合分词结果: {tokens}")


@requires_nltk
def test_stemming_functionality(tokenizer):
    """测试词干提取功能（需要 NLTK PorterStemmer）"""
    # 测试常见的词形变化
    test_cases = {
        "running": "run",
        "jumped": "jump",
        "flies": "fli",  # fly → fli (PorterStemmer 规则)
        "learning": "learn",
        "studies": "studi",  # study → studi
    }

    for original, expected_stem in test_cases.items():
        tokens = tokenizer.tokenize(original, enable_english_enhancement=True)
        assert len(tokens) > 0
        assert tokens[0] == expected_stem, f"{original} 应该被词干化为 {expected_stem}，实际: {tokens[0]}"

    print(" 词干提取测试通过")


@requires_nltk
def test_stopword_filtering(tokenizer):
    """测试停用词过滤（需要 NLTK）"""
    text = "The and is are was were been being have has had do does did"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    # 所有常见停用词都应被过滤
    common_stopwords = [
        "the",
        "and",
        "is",
        "are",
        "was",
        "were",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
    ]
    for stopword in common_stopwords:
        assert stopword not in tokens, f"停用词 '{stopword}' 应该被过滤"

    print(" 停用词过滤测试通过")


def test_backward_compatibility(tokenizer):
    """测试向后兼容性：原有方法不受影响"""
    text = "Python 机器学习"

    # tokenize 应该支持简单模式
    simple_tokens = tokenizer.tokenize(text, mode="simple", enable_english_enhancement=False)
    assert len(simple_tokens) > 0

    # tokenize 应该支持搜索模式
    search_tokens = tokenizer.tokenize(text, mode="search", enable_english_enhancement=False)
    assert len(search_tokens) > 0

    print(" 向后兼容性测试通过")
    print(f"   - tokenize_simple: {simple_tokens}")
    print(f"   - tokenize_for_search: {search_tokens}")


def test_special_characters(tokenizer):
    """测试特殊字符处理"""
    text = "hello-world, don't worry! machine_learning"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    assert any("hello" in t or "world" in t for t in tokens)
    if _HAS_NLTK:
        assert any("worri" in t for t in tokens)
    else:
        assert any("worry" in t.lower() or "don't" in t.lower() for t in tokens)


def test_empty_and_whitespace(tokenizer):
    """测试空字符串和空白字符"""
    assert tokenizer.tokenize("") == []
    assert tokenizer.tokenize("   ") == []
    assert tokenizer.tokenize("\n\t  \n") == []

    print(" 空字符串处理测试通过")


@pytest.mark.asyncio
async def test_async_preload(tokenizer):
    """测试异步预加载"""
    await tokenizer.preload(enable_english_enhancement=True)

    # 预加载后应该能正常使用
    tokens = tokenizer.tokenize("test preload", enable_english_enhancement=True)
    assert len(tokens) > 0

    print(" 异步预加载测试通过")


@requires_nltk
def test_real_world_query(tokenizer):
    """测试真实查询场景（需要 NLTK 停用词过滤）"""
    # 模拟用户搜索查询
    queries = [
        "how to use Python for machine learning",
        "深度学习 deep learning tutorial",
        "自然语言处理 NLP techniques",
    ]

    for query in queries:
        tokens = tokenizer.tokenize(query, enable_english_enhancement=True)
        print(f"\n查询: {query}")
        print(f"分词: {tokens}")

        # 基本断言：应该有分词结果
        assert len(tokens) > 0

        # 停用词应被过滤
        assert "to" not in tokens
        assert "for" not in tokens

    print("\n 真实查询测试通过")


if __name__ == "__main__":
    # 手动运行测试
    service = get_tokenizer_service()

    print("=" * 60)
    print("英文分词增强功能测试")
    print("=" * 60)

    test_english_word_detection(service)
    test_simple_english_tokenization(service)
    test_chinese_tokenization(service)
    test_mixed_language_tokenization(service)
    test_stemming_functionality(service)
    test_stopword_filtering(service)
    test_backward_compatibility(service)
    test_special_characters(service)
    test_empty_and_whitespace(service)
    test_real_world_query(service)

    print("\n" + "=" * 60)
    print(" 所有测试通过！")
    print("=" * 60)
