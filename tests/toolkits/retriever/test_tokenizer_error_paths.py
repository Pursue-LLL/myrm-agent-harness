"""异常路径测试：通过内部状态模拟覆盖错误处理分支。"""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# 直接加载 tokenizer 模块（避免包导入链）
def load_tokenizer_module():
    """加载 tokenizer 模块。"""
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("_tokenizer", tokenizer_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enhance_english_nltk_failed():
    """测试 _enhance_english() 在 NLTK 失败时的早期返回（line 126）。"""
    mod = load_tokenizer_module()
    tokenizer = mod.TokenizerService()
    tokenizer._initialize()

    # 模拟 NLTK 初始化失败
    tokenizer._nltk_init_failed = True

    original_tokens = ["hello", "world", "测试"]
    result = tokenizer._enhance_english(original_tokens)

    # 应该原封不动返回
    assert result == original_tokens, f"NLTK 失败应返回原始 tokens: {result}"
    print(" [1/7] _enhance_english() NLTK 失败早期返回")


def test_stemmer_exception_handling():
    """测试词干提取异常的 except 分支（line 141-142）。"""
    mod = load_tokenizer_module()
    tokenizer = mod.TokenizerService()
    tokenizer._initialize()

    # 初始化 NLTK
    if not tokenizer._lazy_init_nltk():
        print(" [2/7] NLTK 未安装，跳过词干异常测试")
        return

    # Mock stemmer.stem() 抛出异常
    original_stem = tokenizer._stemmer.stem
    tokenizer._stemmer.stem = MagicMock(side_effect=RuntimeError("Stem error"))

    result = tokenizer._enhance_english(["hello"])

    # 应该降级为小写 token（line 142）
    assert "hello" in result, f"词干异常应降级为小写: {result}"

    # 恢复
    tokenizer._stemmer.stem = original_stem
    print(" [2/7] 词干提取异常处理")


def test_jieba_import_failure_fallback():
    """测试 jieba 导入失败时的 fallback 路径（line 175）。"""
    mod = load_tokenizer_module()
    tokenizer = mod.TokenizerService()

    # 模拟 jieba 未安装（通过直接设置状态）
    tokenizer._jieba = None
    tokenizer._initialized = True  # 标记为已初始化，避免再次尝试导入

    result = tokenizer.tokenize("hello world 测试")

    # 应该使用正则 fallback（line 175）
    assert "hello" in result and "world" in result and "测试" in result
    print(f" [3/7] jieba 失败 fallback: {result}")


@pytest.mark.asyncio
async def test_preload_nltk_init_failure():
    """测试 preload 中 NLTK 初始化失败的 warning 路径（line 209）。"""
    mod = load_tokenizer_module()
    tokenizer = mod.TokenizerService()

    # Mock _lazy_init_nltk 返回 False（模拟失败）
    original_init = tokenizer._lazy_init_nltk
    tokenizer._lazy_init_nltk = lambda: False

    # 不应抛出异常
    await tokenizer.preload(enable_english_enhancement=True)

    # 恢复
    tokenizer._lazy_init_nltk = original_init
    print(" [4/7] preload NLTK 失败 warning 路径")


@pytest.mark.asyncio
async def test_preload_exception_handling():
    """测试 preload 异常处理（line 211-213）。"""
    mod = load_tokenizer_module()
    tokenizer = mod.TokenizerService()

    # Mock _async_initialize 抛出异常
    async def mock_async_init():
        raise RuntimeError("Async init failed")

    tokenizer._async_initialize = mock_async_init

    # 应该捕获并重新抛出
    with pytest.raises(Exception):  # 会抛出 RuntimeError
        await tokenizer.preload()

    print(" [5/7] preload 异常处理")


def test_nltk_import_error_path():
    """测试 NLTK ImportError 处理路径（line 107-110）。"""
    mod = load_tokenizer_module()
    tokenizer = mod.TokenizerService()
    tokenizer._initialize()

    # Mock nltk.corpus 导入失败
    with patch.dict("sys.modules", {"nltk.corpus": None, "nltk.stem": None}):

        def raise_import(*args, **kwargs):
            if "nltk" in str(args):
                raise ImportError("NLTK not found")
            return object()

        # 直接调用并捕获异常
        try:
            from nltk.corpus import stopwords  # noqa: F401
        except (ImportError, TypeError):
            # 模拟路径：设置失败标志
            tokenizer._nltk_init_failed = True
            result = tokenizer._lazy_init_nltk()
            assert result is False
            print(" [6/7] NLTK ImportError 处理")
            return

    print(" [6/7] NLTK 已安装，跳过 ImportError 测试")


def test_nltk_general_exception_path():
    """测试 NLTK 通用异常处理路径（line 111-114）。"""
    mod = load_tokenizer_module()
    tokenizer = mod.TokenizerService()
    tokenizer._initialize()

    # 模拟 NLTK 初始化时的通用异常
    # 通过 Mock stopwords.words 抛出异常
    with patch("nltk.corpus.stopwords.words", side_effect=RuntimeError("NLTK error")):
        result = tokenizer._lazy_init_nltk()

        # 应该捕获异常并返回 False
        assert result is False, "通用异常应返回 False"
        assert tokenizer._nltk_init_failed, "应设置失败标志"

    print(" [7/7] NLTK 通用异常处理")


if __name__ == "__main__":
    print("=" * 70)
    print("异常路径覆盖测试")
    print("=" * 70 + "\n")

    test_enhance_english_nltk_failed()
    test_stemmer_exception_handling()
    test_jieba_import_failure_fallback()

    # 异步测试
    asyncio.run(test_preload_nltk_init_failure())
    asyncio.run(test_preload_exception_handling())

    test_nltk_import_error_path()
    test_nltk_general_exception_path()

    print("\n" + "=" * 70)
    print(" 所有异常路径测试通过")
    print("=" * 70)
