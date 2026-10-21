from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_outline import (
    extract_truncated_outline,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_truncation import (
    truncate_file_output,
)


def test_python_ast_outline_extraction():
    content = """def func_early():
    pass

class DataService:
    def fetch_all(self):
        pass

    async def save_record(self, data: dict):
        pass

async def process_queue():
    pass
"""
    # Gutter-formatted representation
    lines = content.split("\n")
    gutter_content = "\n".join(f"{i:6}|{line}" for i, line in enumerate(lines, start=1))

    # Request outline from line 4 onwards (should skip func_early)
    outline = extract_truncated_outline(gutter_content, "services/data.py", next_offset=4)
    assert "[OUTLINE OF REMAINING SYMBOLS (from line 4)]:" in outline
    assert "class DataService" in outline
    assert "def DataService.fetch_all" in outline
    assert "async def DataService.save_record" in outline
    assert "async def process_queue" in outline
    assert "func_early" not in outline


def test_python_ast_fallback_on_syntax_error():
    broken_content = """# Incomplete/broken syntax
def valid_func():
    pass

class BrokenClass
    def method():
        pass
"""
    outline = extract_truncated_outline(broken_content, "test.py", next_offset=2)
    assert "[OUTLINE OF REMAINING SYMBOLS (from line 2)]:" in outline
    assert "def valid_func" in outline


def test_typescript_outline_extraction():
    ts_content = """import React from 'react';

export interface UserConfig {
    id: string;
}

export type ThemeMode = 'dark' | 'light';

export enum Status {
    ACTIVE,
    INACTIVE,
}

export class UserManager {
    render() {}
}

export async function fetchUser(id: string) {
    return null;
}

export const calculateScore = (a: number) => {
    return a * 2;
};
"""
    outline = extract_truncated_outline(ts_content, "src/components/User.tsx", next_offset=3)
    assert "[OUTLINE OF REMAINING SYMBOLS (from line 3)]:" in outline
    assert "interface UserConfig" in outline
    assert "type ThemeMode" in outline
    assert "enum Status" in outline
    assert "class UserManager" in outline
    assert "function fetchUser" in outline
    assert "const calculateScore" in outline


def test_go_and_rust_outline_extraction():
    go_content = """package main

type ServerConfig struct {
    Port int
}

func (s *ServerConfig) Start() error {
    return nil
}

func HandleRequest() {
}
"""
    outline_go = extract_truncated_outline(go_content, "server.go", next_offset=3)
    assert "type ServerConfig" in outline_go
    assert "func Start" in outline_go
    assert "func HandleRequest" in outline_go

    rs_content = """pub struct Database {
    conn: String,
}

impl Database {
    pub async fn connect() {}
}

pub fn helper() {}
"""
    outline_rs = extract_truncated_outline(rs_content, "db.rs", next_offset=1)
    assert "struct Database" in outline_rs
    assert "impl Database" in outline_rs
    assert "fn helper" in outline_rs


def test_max_symbols_truncation_fuse():
    # Generate 35 functions
    py_lines = [f"def function_{i}():\n    pass\n" for i in range(1, 36)]
    content = "\n".join(py_lines)

    outline = extract_truncated_outline(content, "many.py", next_offset=1, max_symbols=15)
    assert "[OUTLINE OF REMAINING SYMBOLS (from line 1)]:" in outline
    assert "def function_1" in outline
    assert "def function_15" in outline
    assert "def function_16" not in outline
    assert "... and 20 more symbols." in outline


def test_comments_are_ignored_in_regex_extraction():
    ts_content = """// function commented_out() {}
/*
 * class IgnoredClass {}
 */
# def ignored_python_comment():
export function realFunction() {}
"""
    outline = extract_truncated_outline(ts_content, "code.ts", next_offset=1)
    assert "realFunction" in outline
    assert "commented_out" not in outline
    assert "IgnoredClass" not in outline
    assert "ignored_python_comment" not in outline


def test_non_code_files_return_empty_outline():
    text_content = "Some plain text\nAnother line\nYet another line"
    assert extract_truncated_outline(text_content, "readme.md", next_offset=2) == ""
    assert extract_truncated_outline(text_content, "data.csv", next_offset=2) == ""
    assert extract_truncated_outline(text_content, "log.txt", next_offset=2) == ""


def test_markdown_outline_extraction():
    from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_outline import (
        extract_file_outline,
    )

    md_content = """# Architecture Overview
Some intro text.
## 1. System Components
Details about components.
### 1.1 Storage Layer
SQLite details.
## 2. API Endpoints
Endpoints description.
"""
    outline = extract_file_outline(md_content, "docs/arch.md")
    assert "[DOCUMENT STRUCTURE OUTLINE: arch.md]:" in outline
    assert "- Line 1: # Architecture Overview" in outline
    assert "- Line 3: ## 1. System Components" in outline
    assert "- Line 5: ### 1.1 Storage Layer" in outline
    assert "- Line 7: ## 2. API Endpoints" in outline


def test_markdown_outline_ignores_code_block_comments():
    from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_outline import (
        extract_file_outline,
    )

    md_content = """# Guide Title

Here is how you configure the service:

```python
# This is a python configuration comment
def setup():
    # Another nested comment
    pass
```

~~~bash
# Bash script comment
curl -X POST http://localhost:8080
~~~

## Next Steps
Conclusion text.
"""
    outline = extract_file_outline(md_content, "guide.md")
    assert "- Line 1: # Guide Title" in outline
    assert "- Line 17: ## Next Steps" in outline
    assert "This is a python configuration comment" not in outline
    assert "Another nested comment" not in outline
    assert "Bash script comment" not in outline


def test_markdown_outline_ignores_indented_code_comments():
    from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_outline import (
        extract_file_outline,
    )

    md_content = """# Guide Title

    # indented python comment
    x = 1

## Next Steps
"""
    outline = extract_file_outline(md_content, "guide.md")
    assert "- Line 1: # Guide Title" in outline
    assert "- Line 6: ## Next Steps" in outline
    assert "indented python comment" not in outline


def test_markdown_outline_ignores_yaml_frontmatter_comments():
    from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_outline import (
        extract_file_outline,
    )

    md_content = """---
title: Sample Post
# This is a yaml frontmatter comment
author: Admin
---

# Real Heading
Intro paragraph.
"""
    outline = extract_file_outline(md_content, "post.md")
    assert "- Line 7: # Real Heading" in outline
    assert "This is a yaml frontmatter comment" not in outline


def test_truncate_file_output_appends_outline():
    long_python = "\n".join(
        [f"{i:6}|# comment {i}" for i in range(1, 100)]
        + [
            f"{100:6}|class TargetController:",
            f"{101:6}|    def handle_target(self):",
            f"{102:6}|        pass",
        ]
    )
    truncated, was_truncated, _meta = truncate_file_output(
        long_python,
        max_chars=200,
        is_dir=False,
        path_str="controller.py",
    )
    assert was_truncated is True
    assert "[SYSTEM WARNING: Output capped" in truncated
    assert "[OUTLINE OF REMAINING SYMBOLS" in truncated
    assert "class TargetController" in truncated
    assert "def TargetController.handle_target" in truncated
