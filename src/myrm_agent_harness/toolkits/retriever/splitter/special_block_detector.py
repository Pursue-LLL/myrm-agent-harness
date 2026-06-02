"""[INPUT]
- (none)

[OUTPUT]
- SpecialBlockDetector: class — Special Block Detector
- hello: import re

[POS]
Provides SpecialBlockDetector, hello.
"""

import re

r"""Special block detection module

Identifies and extracts special structures in text（code blocks, tables, lists）

## Description

When splitting Markdown text, the integrity of the following structures must be protected：

### 1. Code blocks
```markdown
```python
def hello():
    print("world")
```
```
Cannot split in the middle of a code block, or code semantics will be broken。

### 2. Table
```markdown
| Col1 | Col2 |
|-----|-----|
| A   | B   |
```
Table must Contains表头、分隔行 and Data行， not 能拆散。

### 3. Lists (including nested)
```markdown
- Item1
  - Sub-item1.1
  - Sub-item1.2
- Item2
```
List项 and Sub-item need 保持 in 一起。

## Usage example

```python
detector = SpecialBlockDetector()

text = '''
# Heading

普通text。

\`\`\`python
code here
\`\`\`

| A | B |
|---|---|
| 1 | 2 |
'''

# 检测AllSpecial block
blocks = detector.extract_special_structures(text)
# Return: [
#   {"type": "code", "start": 20, "end": 50, "language": "python", "content": "code here"},
#   {"type": "table", "start": 52, "end": 80, "content": "| A | B |\\n|---|---|\\n| 1 | 2 |"}
# ]
```

## 检测Rule

- **Code blocks**: Match \`\`\`language...content...\`\`\`
- **Table**: 表头行 + 分隔行（|---|---）+ Data行
- **List**: 以 `-`、`*`、`+`  or  `1.` 开头，Support缩进识别嵌套
"""


class SpecialBlockDetector:
    """Special block detector"""

    def __init__(self):
        # Pre-compiled regex patterns
        self._list_item_pattern = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")
        self._code_fence_pattern = re.compile(r"```(\w*)\n([\s\S]*?)```", re.MULTILINE)
        self._table_separator_pattern = re.compile(r"^[\s|:-]+\|[\s|:-]+$")

    def extract_special_structures(self, text: str) -> list[dict]:
        """ExtractAll特殊结构（code blocks, tables, lists）

        Args:
            text: 待检测text

        Returns:
            特殊结构informationList，按startPositionSort
        """
        special_structures = []

        # MatchCode blocks
        for m in self._code_fence_pattern.finditer(text):
            special_structures.append(
                {
                    "type": "code",
                    "start": m.start(),
                    "end": m.end(),
                    "language": m.group(1) or "",
                    "content": m.group(2),
                }
            )

        # MatchTable
        table_structures = self._extract_tables(text)
        special_structures.extend(table_structures)

        # MatchList
        list_structures = self._extract_lists(text)
        special_structures.extend(list_structures)

        special_structures.sort(key=lambda x: x["start"])
        return special_structures

    def _extract_tables(self, text: str) -> list[dict]:
        """ExtractTable结构

        识别Rule：表头行 + 分隔行（|:-:|） + Data行

        Args:
            text: 待检测text

        Returns:
            Table结构informationList
        """
        table_structures = []
        lines = text.split("\n")
        i = 0

        while i < len(lines):
            if i + 1 < len(lines):
                current_line = lines[i]
                next_line = lines[i + 1]

                if "|" in current_line and self._table_separator_pattern.match(next_line):
                    table_start_line_idx = i
                    table_lines = [current_line, next_line]
                    j = i + 2

                    # 收集后续 TableData行
                    while j < len(lines) and "|" in lines[j] and lines[j].strip():
                        table_lines.append(lines[j])
                        j += 1

                    # ComputeCharactersPosition
                    chars_before = sum(len(lines[k]) + 1 for k in range(table_start_line_idx))
                    table_content = "\n".join(table_lines)

                    table_structures.append(
                        {
                            "type": "table",
                            "start": chars_before,
                            "end": chars_before + len(table_content),
                            "content": table_content,
                        }
                    )

                    i = j
                    continue
            i += 1

        return table_structures

    def _extract_lists(self, text: str) -> list[dict]:
        """ExtractList结构（including嵌套List）

        识别Rule：
        -  has 序List：以数字+点+Empty格开头（如 "1. "、"2. "）
        -  no 序List：以 "- "、"* "、"+ " 开头
        - 嵌套List： via 缩进判断（2 or 4个Empty格）

        Args:
            text: 待检测text

        Returns:
            List结构informationList
        """
        list_structures = []
        lines = text.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i]
            match = self._list_item_pattern.match(line)

            if match:
                # 找 to ListStart
                list_start_idx = i
                list_lines = []
                base_indent = len(match.group(1))  # basic缩进

                # 收集complete List（including嵌套项 and 延续行）
                j = i
                while j < len(lines):
                    current_line = lines[j]
                    current_match = self._list_item_pattern.match(current_line)

                    if not current_line.strip():
                        # Empty行，可能是ListEnd，也可能是List内 Empty行
                        if j + 1 < len(lines):
                            next_line = lines[j + 1]
                            next_match = self._list_item_pattern.match(next_line)
                            if next_match:
                                # 下一行还是List项，保留Empty行
                                list_lines.append(current_line)
                                j += 1
                                continue
                        # OtherwiseListEnd
                        break

                    if current_match:
                        # List项
                        current_indent = len(current_match.group(1))
                        if current_indent < base_indent:
                            # 缩进减少，回 to 上一级List or ListEnd
                            break
                        # 同级 or 子级List项
                        list_lines.append(current_line)
                    else:
                        # 非List项行
                        # CheckWhether是List项 延续（缩进）
                        if current_line.startswith(" " * (base_indent + 2)):
                            # 缩进延续，属于List项Content
                            list_lines.append(current_line)
                        else:
                            # ListEnd
                            break

                    j += 1

                if list_lines:
                    # ComputeStartCharactersPosition
                    chars_before = sum(len(lines[k]) + 1 for k in range(list_start_idx))
                    list_content = "\n".join(list_lines)

                    list_structures.append(
                        {
                            "type": "list",
                            "start": chars_before,
                            "end": chars_before + len(list_content),
                            "content": list_content,
                        }
                    )

                    i = j
                    continue

            i += 1

        return list_structures

    def is_table_separator_line(self, line: str) -> bool:
        """CheckWhether是Table分隔行"""
        return bool(self._table_separator_pattern.match(line.strip()))

    def is_list_item_line(self, line: str) -> bool:
        """CheckWhether是List项行"""
        return bool(self._list_item_pattern.match(line))

    def get_list_item_indent(self, line: str) -> int:
        """GetList项 缩进Length"""
        match = self._list_item_pattern.match(line)
        return len(match.group(1)) if match else -1
