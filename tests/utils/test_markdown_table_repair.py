"""Tests for Markdown table sanitizer and repair engine."""

import unittest
from myrm_agent_harness.utils.markdown_table_repair import repair_markdown_tables


class TestMarkdownTableRepair(unittest.TestCase):

    def test_missing_header_divider(self):
        """Case 1: LLM outputs header and data rows but completely omits the divider row (|---|---|)."""
        dirty = """Here is the financial breakdown:
| Metric | Q1 | Q2 |
| Revenue | $10M | $12M |
| Profit | $2M | $3M |
That concludes the summary."""

        repaired = repair_markdown_tables(dirty)
        expected_table = """| Metric | Q1 | Q2 |
| --- | --- | --- |
| Revenue | $10M | $12M |
| Profit | $2M | $3M |"""
        self.assertIn(expected_table, repaired)
        # Verify paragraph isolation
        self.assertIn("Here is the financial breakdown:\n\n|", repaired)
        self.assertIn("|\n\nThat concludes the summary.", repaired)

    def test_fullwidth_pipe_chinese(self):
        """Case 2: Chinese LLM outputs fullwidth pipe '｜' instead of ASCII '|'."""
        dirty = """｜ 姓名 ｜ 年龄 ｜ 部门 ｜
｜ 张三 ｜ 28 ｜ 研发部 ｜
｜ 李四 ｜ 34 ｜ 市场部 ｜"""

        repaired = repair_markdown_tables(dirty)
        self.assertIn("| 姓名 | 年龄 | 部门 |", repaired)
        self.assertIn("| --- | --- | --- |", repaired)
        self.assertIn("| 张三 | 28 | 研发部 |", repaired)
        self.assertIn("| 李四 | 34 | 市场部 |", repaired)

    def test_missing_leading_and_trailing_pipes(self):
        """Case 3: LLM omits leading and trailing pipes on rows."""
        dirty = """Name | Role | Location
--- | --- | ---
Alice | Tech Lead | San Francisco
Bob | Designer | New York"""

        repaired = repair_markdown_tables(dirty)
        self.assertIn("| Name | Role | Location |", repaired)
        self.assertIn("| --- | --- | --- |", repaired)
        self.assertIn("| Alice | Tech Lead | San Francisco |", repaired)
        self.assertIn("| Bob | Designer | New York |", repaired)

    def test_mismatched_column_counts(self):
        """Case 4: Data rows have missing columns (padded) or excessive columns."""
        dirty = """| ID | Product | Price | Stock |
| :--- | :---: | ---: | :--- |
| P01 | Apple | $1.50 |
| P02 | Banana | $0.80 | 120 | ExtraNote |
| P03 | Orange |"""

        repaired = repair_markdown_tables(dirty)
        # Row P01 should be padded with empty column to 4 cols
        self.assertIn("| P01 | Apple | $1.50 |   |", repaired)
        # Row P02 should be truncated/normalized to 4 cols
        self.assertIn("| P02 | Banana | $0.80 | 120 |", repaired)
        # Row P03 should be padded to 4 cols
        self.assertIn("| P03 | Orange |   |   |", repaired)

    def test_cell_with_code_pipe_protected(self):
        """Case 5: Cell contains code blocks or inline code with pipes (e.g. `ls | grep foo`)."""
        dirty = """| Command | Description |
| --- | --- |
| `cat file.txt | grep error` | Filter errors |
| `true || false` | Logical OR |"""

        repaired = repair_markdown_tables(dirty)
        self.assertIn("| `cat file.txt | grep error` | Filter errors |", repaired)
        self.assertIn("| `true || false` | Logical OR |", repaired)

    def test_multiline_cell_newlines_sanitized(self):
        """Case 6: Cell contents contain embedded newlines."""
        dirty = """| Task | Details |
| --- | --- |
| Database migration | Step 1: Backup
Step 2: Run DDL"""

        repaired = repair_markdown_tables(dirty)
        self.assertIn("| Database migration | Step 1: Backup<br>Step 2: Run DDL |", repaired)

    def test_truncated_streaming_incomplete_table(self):
        """Case 7: LLM streaming gets cut off mid-table."""
        # Only header so far in streaming mode
        streaming_header_only = "| Feature | Complexity | Priority |"
        repaired_stream = repair_markdown_tables(streaming_header_only, is_streaming=True)
        self.assertIn("| Feature | Complexity | Priority |", repaired_stream)
        self.assertIn("| --- | --- | --- |", repaired_stream)

    def test_code_block_fences_completely_shielded(self):
        """Case 8: Fenced code blocks containing markdown table examples must NOT be altered."""
        dirty = """Before code.

```markdown
Some example:
| a | b |
| 1 |
```

After code."""

        repaired = repair_markdown_tables(dirty)
        # The inner table inside ```markdown must remain untouched
        self.assertIn("| a | b |\n| 1 |", repaired)
        self.assertIn("Before code.", repaired)
        self.assertIn("After code.", repaired)

    def test_malformed_divider_row(self):
        """Case 9: Divider row has malformed hyphens or incorrect column count."""
        dirty = """| Col A | Col B | Col C |
| - | --: |
| val1 | val2 | val3 |"""

        repaired = repair_markdown_tables(dirty)
        # Divider should be repaired to 3 columns and valid hyphens
        self.assertIn("| Col A | Col B | Col C |", repaired)
        self.assertIn("| --- | ---: | --- |", repaired)
        self.assertIn("| val1 | val2 | val3 |", repaired)

    def test_real_world_dirty_llm_markdown_table(self):
        """Case 10: Highly complex realistic dirty output with missing pipes, comments, and unaligned rows."""
        dirty = """根据您的财务指标查询，各季度表现如下：
指标 ｜ Q1 ｜ Q2 ｜ 备注
--- ｜ :---: ｜ ---:
总营收 | 1200万元 | 1450万元 | 同比增长20%
净利润 | 300万元 | 420万元
每股收益 ｜ 0.52元 ｜ 0.68元 ｜ 稳定增长
以上为初步审计结果。"""

        repaired = repair_markdown_tables(dirty)
        self.assertIn("| 指标 | Q1 | Q2 | 备注 |", repaired)
        self.assertIn("| --- | :---: | ---: | --- |", repaired)
        self.assertIn("| 总营收 | 1200万元 | 1450万元 | 同比增长20% |", repaired)
        self.assertIn("| 净利润 | 300万元 | 420万元 |", repaired)
        self.assertIn("| 每股收益 | 0.52元 | 0.68元 | 稳定增长 |", repaired)
        self.assertIn("根据您的财务指标查询，各季度表现如下：\n\n|", repaired)


if __name__ == "__main__":
    unittest.main()

