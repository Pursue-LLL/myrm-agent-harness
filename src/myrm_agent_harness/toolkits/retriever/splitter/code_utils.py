"""代码related ToolFunction

provides代码语言检测、Code blocks保护、AST智能分割 etc.功能

[INPUT]
- (none)

[OUTPUT]
- detect_code_language: Args:
- split_large_code_block: Args:
- protect_code_blocks: Args:
- restore_code_blocks: RestoreCode blocks

[POS]
Provides detect_code_language, split_large_code_block, protect_code_blocks.
"""

import logging
import re

logger = logging.getLogger(__name__)

_RETRIEVAL_INSTALL_HINT = (
    "langchain-text-splitters is required for code-aware splitting. "
    "Install with: pip install 'myrm-agent-harness[retrieval]'"
)


def _get_langchain_splitters():
    try:
        from langchain_text_splitters import Language, RecursiveCharacterTextSplitter
    except ImportError as exc:
        raise ImportError(_RETRIEVAL_INSTALL_HINT) from exc
    return Language, RecursiveCharacterTextSplitter

# 语言映射表（映射 to langchain Language枚举）
LANGUAGE_MAP = {
    "cpp": "cpp",
    "c++": "cpp",
    "c": "c",
    "csharp": "csharp",
    "c#": "csharp",
    "cobol": "cobol",
    "elixir": "elixir",
    "go": "go",
    "golang": "go",
    "haskell": "haskell",
    "html": "html",
    "java": "java",
    "js": "js",
    "javascript": "js",
    "jsx": "js",
    "kotlin": "kotlin",
    "latex": "latex",
    "lua": "lua",
    "markdown": "markdown",
    "md": "markdown",
    "perl": "perl",
    "php": "php",
    "powershell": "powershell",
    "proto": "proto",
    "python": "python",
    "py": "python",
    "rst": "rst",
    "ruby": "ruby",
    "rb": "ruby",
    "rust": "rust",
    "rs": "rust",
    "scala": "scala",
    "sol": "sol",
    "solidity": "sol",
    "swift": "swift",
    "ts": "ts",
    "typescript": "ts",
    "tsx": "ts",
    "visualbasic6": "visualbasic6",
    "vb6": "visualbasic6",
}


def detect_code_language(code: str) -> str | None:
    """Auto检测代码语言（Only检测langchain from_languageSupport 语言）

    Args:
        code: 代码Content

    Returns:
        检测 to  语言名称，If no 法检测则ReturnNone

    Note:
        只检测langchain RecursiveCharacterTextSplitter.from_languageSupport 语言：
        cpp, go, java, kotlin, js, ts, php, proto, python, rst, ruby, rust,
        scala, swift, markdown, latex, html, sol, csharp, cobol, c, lua,
        perl, haskell, elixir, powershell, visualbasic6
    """
    if not code or len(code.strip()) < 10:
        return None

    # 语言特征Mode（只保留langchainSupport ）
    language_patterns = {
        "python": [
            r"\bdef\s+\w+\s*\(",
            r"\bclass\s+\w+\s*:",
            r"\bimport\s+\w+",
            r"\bfrom\s+\w+\s+import",
        ],
        "js": [
            r"\bfunction\s+\w+\s*\(",
            r"\bconst\s+\w+\s*=",
            r"\blet\s+\w+\s*=",
            r"=>\s*{",
            r"<\w+\s+[^>]*>",  # JSX
        ],
        "ts": [
            r"\binterface\s+\w+\s*{",
            r"\btype\s+\w+\s*=",
            r":\s*(string|number|boolean)",
        ],
        "html": [
            r"<!DOCTYPE\s+html>",
            r"<html[^>]*>",
            r"<head>",
            r"<body[^>]*>",
        ],
        "java": [
            r"\bpublic\s+class\s+\w+",
            r"\bprivate\s+\w+\s+\w+",
            r"\bpublic\s+static\s+void\s+main",
        ],
        "go": [
            r"\bfunc\s+\w+\s*\(",
            r"\bpackage\s+\w+",
            r"\btype\s+\w+\s+struct",
        ],
        "rust": [
            r"\bfn\s+\w+\s*\(",
            r"\blet\s+mut\s+",
            r"\bimpl\s+\w+",
        ],
        "ruby": [
            r"\bdef\s+\w+",
            r"\bclass\s+\w+\s*<",
            r"\bend\b",
        ],
        "cpp": [
            r"#include\s+<",
            r"\bclass\s+\w+\s*{",
            r"std::",
        ],
        "csharp": [
            r"\bnamespace\s+\w+",
            r"\bpublic\s+class\s+\w+",
            r"using\s+System",
        ],
        "php": [
            r"<\?php",
            r"\$\w+\s*=",
            r"function\s+\w+\s*\(",
        ],
    }

    # Statistics每种语言 Match数
    scores = {}
    for lang, patterns in language_patterns.items():
        score = 0
        for pattern in patterns:
            if re.search(pattern, code, re.MULTILINE):
                score += 1
        if score > 0:
            scores[lang] = score

    if not scores:
        return None

    # 特殊Process：HTML优先（ avoid  and JSX混淆）
    if "html" in scores and scores["html"] >= 3:
        detected_lang = "html"
    else:
        # Return得分最高 语言
        detected_lang = max(scores.items(), key=lambda x: x[1])[0]

    logger.warning(f"Auto检测代码语言: {detected_lang} (Match度: {scores[detected_lang]})")
    return detected_lang


def split_large_code_block(code_content: str, language: str, max_tokens: int = 2000) -> list[str]:
    """对大型Code blocks using ASTPerform智能分割

    Args:
        code_content: 代码Content（ not including```标记）
        language: 代码语言
        max_tokens: Maximumtoken数阈Value

    Returns:
        分割后 代码片段List
    """
    from myrm_agent_harness.utils.text_utils import get_token_count

    code_tokens = get_token_count(code_content)
    if code_tokens <= max_tokens:
        return [code_content]

    lang_key = LANGUAGE_MAP.get(language.lower())
    if not lang_key:
        logger.warning(f" not Support 代码语言: {language}， using simple行分割")
        return _split_by_lines(code_content, max_tokens)

    try:
        Language, RecursiveCharacterTextSplitter = _get_langchain_splitters()
        splitter = RecursiveCharacterTextSplitter.from_language(
            language=Language[lang_key.upper()],
            chunk_size=max_tokens,
            chunk_overlap=int(max_tokens * 0.1),
        )

        chunks = splitter.split_text(code_content)
        logger.warning(f"AST分割大型{language}Code blocks: {code_tokens}Token -> {len(chunks)}个片段")
        return chunks

    except Exception as e:
        logger.warning(f"AST分割Failure: {e!s}，保持Code blockscomplete")
        return [code_content]


def _split_by_lines(code_content: str, max_tokens: int) -> list[str]:
    """按行simple分割代码"""
    from myrm_agent_harness.utils.text_utils import get_token_count

    lines = code_content.split("\n")
    chunks = []
    current_chunk = []
    current_tokens = 0

    for line in lines:
        line_tokens = get_token_count(line)
        if current_tokens + line_tokens > max_tokens and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_tokens = line_tokens
        else:
            current_chunk.append(line)
            current_tokens += line_tokens

    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


def protect_code_blocks(text: str, max_chunk_tokens: int = 675) -> tuple[str, dict[str, str]]:
    """保护markdownCode blocks not 被分割，对大型Code blocks using AST智能分割

    Args:
        text: originaltext
        max_chunk_tokens: 目标Chunk MaximumToken数

    Returns:
        (Processedtext, 占位符映射Dict)
    """
    code_block_pattern = r"```(\w*)\n([\s\S]*?)```"
    code_blocks = {}
    counter = 0

    def replace_code_block(match):
        nonlocal counter
        language = match.group(1) or ""
        code_content = match.group(2)

        # If没 has 标记语言，尝试Auto检测
        if not language or language in ("text", "txt", ""):
            detected = detect_code_language(code_content)
            if detected:
                language = detected
                logger.warning(f"Code blocks not yet 标记语言，Auto检测 is : {language}")
            else:
                language = "text"

        #  not 预先分割Code blocks,保持complete性
        # IfToken超限, in 整体ChunkStageProcess
        code_chunks = [code_content]

        if len(code_chunks) == 1:
            # 小Code blocks，保持complete( using 修正后 language)
            placeholder = f"__CODE_BLOCK_{counter}__"
            code_blocks[placeholder] = f"```{language}\n{code_content}\n```"
            counter += 1
            return placeholder
        else:
            # 大Code blocks被分割成multiple片段
            placeholders = []
            for chunk in code_chunks:
                placeholder = f"__CODE_BLOCK_{counter}__"
                code_blocks[placeholder] = f"```{language}\n{chunk}\n```"
                placeholders.append(placeholder)
                counter += 1
            logger.warning(f"Code blocks already 分割 is {len(code_chunks)}个片段")
            return "\n\n".join(placeholders)

    protected_text = re.sub(code_block_pattern, replace_code_block, text)
    return protected_text, code_blocks


def restore_code_blocks(text: str, code_blocks: dict[str, str]) -> str:
    """RestoreCode blocks

    Args:
        text: Contains占位符 text
        code_blocks: 占位符映射Dict

    Returns:
        Restore后 text
    """
    for placeholder, code_block in code_blocks.items():
        text = text.replace(placeholder, code_block)
    return text
