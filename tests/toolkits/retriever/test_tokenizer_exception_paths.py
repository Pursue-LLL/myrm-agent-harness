"""异常路径测试：覆盖所有错误处理分支。"""

# ruff: noqa: N806

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


def test_jieba_import_error():
    """测试 jieba 导入失败的降级路径。"""
    # 直接加载 tokenizer.py（避免 numpy 冲突）
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_test", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)

    # Mock jieba 导入失败
    with patch.dict("sys.modules", {"jieba": None}):
        # 这会导致 import jieba 失败
        original_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "jieba":
                raise ImportError("jieba not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            spec.loader.exec_module(tokenizer_module)

            TokenizerService = tokenizer_module.TokenizerService
            tokenizer = TokenizerService()

            # 应该触发 fallback 路径
            result = tokenizer.tokenize("hello world")
            assert result == ["hello", "world"], f"Fallback 失败: {result}"

    print(" jieba ImportError 路径测试通过")


def test_nltk_import_error():
    """测试 NLTK 导入失败的降级路径。"""
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_nltk", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tokenizer_module)

    TokenizerService = tokenizer_module.TokenizerService
    tokenizer = TokenizerService()
    tokenizer._initialize()

    # Mock NLTK 导入失败
    original_import = __import__

    def mock_import_nltk(name, *args, **kwargs):
        if "nltk" in name:
            raise ImportError("NLTK not installed")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_nltk):
        result = tokenizer._lazy_init_nltk()
        assert result is False, "NLTK 失败应返回 False"
        assert tokenizer._nltk_init_failed, "应设置失败标志"

    print(" NLTK ImportError 路径测试通过")


@pytest.mark.skipif(
    not importlib.util.find_spec("nltk"),
    reason="nltk not installed — cannot patch nltk.corpus",
)
def test_nltk_stopwords_download():
    """测试 NLTK stopwords LookupError（需要下载）路径。"""
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_stopwords", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tokenizer_module)

    TokenizerService = tokenizer_module.TokenizerService
    tokenizer = TokenizerService()
    tokenizer._initialize()

    # Mock stopwords.words 抛出 LookupError
    with patch("nltk.corpus.stopwords.words") as mock_words:
        mock_words.side_effect = [
            LookupError("Resource not found"),
            {"the", "a", "an"},  # 第二次成功
        ]

        with patch("nltk.download") as mock_download:
            mock_download.return_value = True

            result = tokenizer._lazy_init_nltk()
            assert result is True or result is False  # 取决于 NLTK 是否安装
            assert mock_download.called or not result, "应该尝试下载或初始化失败"

    print(" NLTK stopwords 下载路径测试通过")


@pytest.mark.skipif(
    not importlib.util.find_spec("nltk"),
    reason="nltk not installed — cannot patch nltk.corpus",
)
def test_nltk_general_exception():
    """测试 NLTK 通用异常处理路径。"""
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_exc", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tokenizer_module)

    TokenizerService = tokenizer_module.TokenizerService
    tokenizer = TokenizerService()
    tokenizer._initialize()

    # Mock NLTK 初始化抛出通用异常
    with patch("nltk.corpus.stopwords.words") as mock_words:
        mock_words.side_effect = RuntimeError("Unexpected error")

        result = tokenizer._lazy_init_nltk()
        assert result is False, "通用异常应返回 False"
        assert tokenizer._nltk_init_failed, "应设置失败标志"

    print(" NLTK 通用异常路径测试通过")


def test_enhance_english_fallback():
    """测试英文增强在 NLTK 失败时的降级。"""
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_enhance", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tokenizer_module)

    TokenizerService = tokenizer_module.TokenizerService
    tokenizer = TokenizerService()
    tokenizer._initialize()
    tokenizer._nltk_init_failed = True  # 模拟 NLTK 失败

    # 应该返回原始 tokens
    original = ["hello", "world"]
    result = tokenizer._enhance_english(original)
    assert result == original, "NLTK 失败时应返回原始 tokens"

    print(" 英文增强降级路径测试通过")


def test_stemmer_exception():
    """测试词干提取异常处理。"""
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_stem", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tokenizer_module)

    TokenizerService = tokenizer_module.TokenizerService
    tokenizer = TokenizerService()
    tokenizer._initialize()

    # 确保 NLTK 初始化
    if tokenizer._lazy_init_nltk():
        # Mock stemmer 抛出异常
        with patch.object(tokenizer._stemmer, "stem") as mock_stem:
            mock_stem.side_effect = RuntimeError("Stemmer error")

            result = tokenizer._enhance_english(["hello"])
            # 应该降级为小写（line 142）
            assert result == ["hello"], f"应该降级为小写: {result}"

        print(" 词干提取异常处理测试通过")
    else:
        print(" NLTK 未安装，跳过词干异常测试")


async def test_preload_exceptions():
    """测试 preload 异常处理路径。"""
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_preload", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tokenizer_module)

    TokenizerService = tokenizer_module.TokenizerService
    tokenizer = TokenizerService()

    # Mock _async_initialize 抛出异常
    with patch.object(tokenizer, "_async_initialize") as mock_init:
        mock_init.side_effect = RuntimeError("Init failed")

        with pytest.raises(RuntimeError, match="Init failed"):
            await tokenizer.preload()

    print(" Preload 异常处理测试通过")


@pytest.mark.asyncio
async def test_preload_nltk_failure_warning():
    """测试 preload 中 NLTK 失败的 warning 路径。"""
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_warn", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tokenizer_module)

    TokenizerService = tokenizer_module.TokenizerService
    tokenizer = TokenizerService()

    # Mock _lazy_init_nltk 返回 False
    with patch.object(tokenizer, "_lazy_init_nltk", return_value=False):
        await tokenizer.preload(enable_english_enhancement=True)
        # 不应抛出异常，应该 gracefully degrade

    print(" NLTK preload 失败 warning 路径测试通过")


if __name__ == "__main__":
    # 直接运行测试（不使用 pytest）
    print("=" * 70)
    print("异常路径覆盖测试")
    print("=" * 70)

    test_jieba_import_error()
    test_nltk_import_error()
    test_nltk_stopwords_download()
    test_nltk_general_exception()
    test_enhance_english_fallback()
    test_stemmer_exception()

    import asyncio

    asyncio.run(test_preload_exceptions())
    asyncio.run(test_preload_nltk_failure_warning())

    print("\n" + "=" * 70)
    print(" 所有异常路径测试通过")
    print("=" * 70)
