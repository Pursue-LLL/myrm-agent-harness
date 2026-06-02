"""Special block splitter module.

Handles splitting of oversized special blocks (code blocks, tables, lists).

## Overview

When a detected special block (code / table / list) exceeds the chunk-size limit,
it is split intelligently:

### 1. Oversized code blocks
Split via AST to preserve code integrity:
```python
# Original oversized code block (exceeds chunk_size)
def func1():
    ...  # 100 lines

def func2():
    ...  # 100 lines

# After splitting
chunk1: complete definition of func1
chunk2: complete definition of func2
```

### 2. Oversized tables
Retain the header row and split data rows:
```markdown
# Original table (100 data rows)
| Col1 | Col2 |
|------|------|
| data rows 1-100 |

# After splitting
chunk1: header + data rows 1-30
chunk2: header + data rows 31-60
chunk3: header + data rows 61-100
```

### 3. Oversized lists
Split by top-level list items, keeping sub-items intact:
```markdown
# Original list
- Item 1
  - Sub-item 1.1
  - Sub-item 1.2
- Item 2
  - Sub-item 2.1

# After splitting
chunk1: Item 1 + all sub-items
chunk2: Item 2 + all sub-items
```

## Usage example

```python
splitter = SpecialBlockSplitter(
    chunk_size=500,
    max_with_special=1000,
    length_function=token_counter,
    detector=detector
)

block = {
    "type": "code",
    "language": "python",
    "content": "...very long code..."  # exceeds 1000 tokens
}

chunks = splitter.handle_special_block(block)
# Returns multiple chunks, each syntactically complete
```

[INPUT]
retriever.splitter.special_block_detector::SpecialBlockDetector (POS: Detects code/table/list special blocks)

[OUTPUT]
SpecialBlockSplitter: Splits oversized code blocks, tables, and lists into token-bounded chunks

[POS]
Special-block splitter. Handles oversized code / table / list blocks that exceed the normal
chunk-size limit, splitting them while preserving structural integrity.

"""

import logging
from collections.abc import Callable

from myrm_agent_harness.toolkits.retriever.splitter.code_utils import detect_code_language, split_large_code_block

from .special_block_detector import SpecialBlockDetector

logger = logging.getLogger(__name__)


class SpecialBlockSplitter:
    """Special block分割器"""

    def __init__(
        self,
        chunk_size: int,
        max_with_special: int,
        length_function: Callable[[str], int],
        detector: SpecialBlockDetector,
    ):
        """Initialize

        Args:
            chunk_size: 目标chunkSize
            max_with_special: Special block allow  MaximumSize
            length_function: Token计数Function
            detector: Special block检测器
        """
        self.chunk_size = chunk_size
        self.max_with_special = max_with_special
        self._length_function = length_function
        self._detector = detector

    def handle_special_block(self, block: dict) -> list[str]:
        """ProcessSpecial block（code blocks, tables, lists）

        Args:
            block: Special blockinformation

        Returns:
            Processed块List
        """
        if block["type"] == "code":
            return self._handle_code_block(block)
        elif block["type"] == "table":
            return self._handle_table_block(block)
        elif block["type"] == "list":
            return self._handle_list_block(block)
        return []

    def _handle_code_block(self, block: dict) -> list[str]:
        """ProcessCode blocks

        Args:
            block: Code blocksinformation

        Returns:
            ProcessedCode blocksList
        """
        language = block.get("language") or ""
        code_body = block.get("content") or ""

        # 检测语言
        detected_lang = language
        if not detected_lang or detected_lang in ("text", "txt"):
            maybe = detect_code_language(code_body)
            if maybe:
                detected_lang = maybe

        code_block_text = self._fenced_code(detected_lang, code_body)
        code_tokens = self._length_function(code_block_text)

        # IfCode blocks太大， need Split
        if code_tokens > self.max_with_special:
            logger.warning(f"超大Code blocks({detected_lang}): {code_tokens}Token，ExecuteASTSplit")

            code_pieces = split_large_code_block(code_body, detected_lang or "text", max_tokens=self.chunk_size)
            return [self._fenced_code(detected_lang, cp) for cp in code_pieces]
        else:
            return [code_block_text]

    def _handle_table_block(self, block: dict) -> list[str]:
        """ProcessTable块

        Args:
            block: Table块information

        Returns:
            ProcessedTable块List
        """
        table_content = block.get("content") or ""
        table_tokens = self._length_function(table_content)

        if table_tokens > self.max_with_special:
            logger.warning(f"超大Table: {table_tokens}Token，ExecuteTableSplit（保留表头）")
            return self._split_large_table(table_content)
        else:
            return [table_content]

    def _handle_list_block(self, block: dict) -> list[str]:
        """ProcessList块

        Strategy:
        - IfListtoken数 <= max_with_special，保持complete
        - Otherwise，尝试按顶级List项分割（保持子项 and 父项 in 一起）

        Args:
            block: List块information

        Returns:
            ProcessedList块List
        """
        list_content = block.get("content") or ""
        list_tokens = self._length_function(list_content)

        if list_tokens <= self.max_with_special:
            return [list_content]

        # List太大，按顶级List项分割
        return self._split_large_list(list_content)

    def _split_large_table(self, table_text: str) -> list[str]:
        """Split超大Table（保留表头）

        Args:
            table_text: Tabletext

        Returns:
            Split后 Table块List
        """
        lines = table_text.strip().split("\n")

        if len(lines) < 3:
            return [table_text]

        header_lines = lines[:2]
        header_text = "\n".join(header_lines)
        header_tokens = self._length_function(header_text)

        data_lines = lines[2:]

        if header_tokens > self.chunk_size * 0.8:
            logger.warning(f"表头过大({header_tokens}Token)， no 法SplitTable")
            return [table_text]

        chunks = []
        current_lines = header_lines[:]
        current_tokens = header_tokens

        for data_line in data_lines:
            line_tokens = self._length_function(data_line)

            if current_tokens + line_tokens > self.chunk_size:
                chunks.append("\n".join(current_lines))
                current_lines = [*header_lines[:], data_line]
                current_tokens = header_tokens + line_tokens
            else:
                current_lines.append(data_line)
                current_tokens += line_tokens

        if len(current_lines) > 2:
            chunks.append("\n".join(current_lines))

        logger.warning(f"TableSplit: original{len(data_lines)}行 -> {len(chunks)}块")
        return chunks

    def _split_large_list(self, list_content: str) -> list[str]:
        """分割超大List（按顶级List项分割，保持子项complete）

        Args:
            list_content: ListContent

        Returns:
            分割后 List块List
        """
        lines = list_content.split("\n")

        # 找 to basic缩进（第一个List项 缩进）
        base_indent = None
        for line in lines:
            if self._detector.is_list_item_line(line):
                base_indent = self._detector.get_list_item_indent(line)
                break

        if base_indent is None:
            #  no 法识别List项，ReturnentireContent
            return [list_content]

        # 按顶级List项分组
        chunks = []
        current_item_lines = []
        current_tokens = 0

        for line in lines:
            if self._detector.is_list_item_line(line):
                indent = self._detector.get_list_item_indent(line)
                if indent == base_indent:
                    # 顶级List项
                    if current_item_lines:
                        # Save前一个List项
                        item_content = "\n".join(current_item_lines)
                        chunks.append(item_content)
                        current_item_lines = []
                        current_tokens = 0

                    current_item_lines.append(line)
                    current_tokens = self._length_function(line)
                else:
                    # 子项
                    current_item_lines.append(line)
                    current_tokens += self._length_function(line)
            else:
                # 延续行
                current_item_lines.append(line)
                current_tokens += self._length_function(line)

        # Save最后一个List项
        if current_item_lines:
            item_content = "\n".join(current_item_lines)
            chunks.append(item_content)

        return chunks if chunks else [list_content]

    @staticmethod
    def _fenced_code(lang: str, body: str) -> str:
        """GenerateCode blockstext

        Args:
            lang: 语言标识
            body: 代码Content

        Returns:
            带围栏 Code blockstext
        """
        return f"```{lang}\n{body}\n```" if lang else f"```\n{body}\n```"
