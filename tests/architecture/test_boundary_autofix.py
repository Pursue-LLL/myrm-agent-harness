"""Tests for auto-fix functionality and error handling in boundary detection.

Validates that the auto-fix mechanism correctly comments out violations
while preserving valid code, and that error conditions are handled gracefully.
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.boundary_engine import (
    collect_imports,
    fix_violations,
)


class TestErrorHandling:
    """Test suite for error handling in boundary check."""

    def test_collect_imports_handles_syntax_error(self) -> None:
        """Test that syntax errors are handled gracefully."""
        invalid_code = """
def incomplete_function(
    # Missing closing parenthesis
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(invalid_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            imports = collect_imports(temp_path)
            assert imports == []
        finally:
            temp_path.unlink()

    def test_collect_imports_handles_unicode_error(self) -> None:
        """Test that encoding errors are handled gracefully."""
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".py", delete=False) as f:
            f.write(b"\xff\xfe Invalid UTF-8")
            f.flush()
            temp_path = Path(f.name)

        try:
            imports = collect_imports(temp_path)
            assert imports == []
        finally:
            temp_path.unlink()

    def test_collect_imports_handles_missing_file(self) -> None:
        """Test that missing files are handled gracefully."""
        non_existent = Path("/tmp/this_file_does_not_exist_12345.py")
        imports = collect_imports(non_existent)
        assert imports == []

    def test_fix_violations_handles_missing_file(self) -> None:
        """Test that fix handles missing files gracefully."""
        non_existent = Path("/tmp/this_file_does_not_exist_12345.py")
        violations = [(1, "myrm_agent_server")]
        fixed_count, fixed_lines = fix_violations(non_existent, violations)
        assert fixed_count == 0
        assert fixed_lines == []


class TestAutoFix:
    """Test suite for auto-fix functionality."""

    def test_fix_single_violation(self) -> None:
        """Test fixing a single boundary violation."""
        test_code = """import os
from myrm_agent_server import database

def main():
    print("hello")
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            violations = [(2, "myrm_agent_server")]
            fixed_count, fixed_lines = fix_violations(temp_path, violations)

            assert fixed_count == 1
            assert len(fixed_lines) == 1
            assert "Line 2:" in fixed_lines[0]

            fixed_content = temp_path.read_text()
            assert "# BOUNDARY-VIOLATION: from myrm_agent_server import database" in fixed_content
            assert "import os" in fixed_content
            assert 'print("hello")' in fixed_content

            ast.parse(fixed_content)
        finally:
            temp_path.unlink()

    def test_fix_multiple_violations(self) -> None:
        """Test fixing multiple boundary violations."""
        test_code = """import os
from myrm_agent_server import database
import myrm_control_plane
from app import config

def main():
    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            violations = [
                (2, "myrm_agent_server"),
                (3, "myrm_control_plane"),
                (4, "app"),
            ]
            fixed_count, fixed_lines = fix_violations(temp_path, violations)

            assert fixed_count == 3
            assert len(fixed_lines) == 3

            fixed_content = temp_path.read_text()
            assert "# BOUNDARY-VIOLATION: from myrm_agent_server import database" in fixed_content
            assert "# BOUNDARY-VIOLATION: import myrm_control_plane" in fixed_content
            assert "# BOUNDARY-VIOLATION: from app import config" in fixed_content

            assert "import os\n" in fixed_content
            assert "def main():" in fixed_content

            ast.parse(fixed_content)
        finally:
            temp_path.unlink()

    def test_fix_preserves_indentation(self) -> None:
        """Test that fix preserves correct indentation."""
        test_code = """def function():
    import os
    from myrm_agent_server import db

    if True:
        import myrm_control_plane
        pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            violations = [(3, "myrm_agent_server"), (6, "myrm_control_plane")]
            fixed_count, _ = fix_violations(temp_path, violations)

            assert fixed_count == 2

            fixed_content = temp_path.read_text()
            lines = fixed_content.split("\n")

            assert lines[2].startswith("    # BOUNDARY-VIOLATION:")
            assert "from myrm_agent_server import db" in lines[2]

            assert lines[5].startswith("        # BOUNDARY-VIOLATION:")
            assert "import myrm_control_plane" in lines[5]

            ast.parse(fixed_content)
        finally:
            temp_path.unlink()

    def test_fix_empty_violations_list(self) -> None:
        """Test that empty violations list doesn't modify file."""
        test_code = """import os

def main():
    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            original_content = test_code
            fixed_count, fixed_lines = fix_violations(temp_path, [])

            assert fixed_count == 0
            assert len(fixed_lines) == 0

            fixed_content = temp_path.read_text()
            assert fixed_content == original_content
        finally:
            temp_path.unlink()

    def test_fix_preserves_valid_code(self) -> None:
        """Test that fix doesn't break valid code after fixing violations."""
        test_code = """from typing import Any
from myrm_agent_server import database
import myrm_agent_harness

def main(x: int) -> str:
    \"\"\"Valid function that should remain intact.\"\"\"
    result = x * 2
    return str(result)

class MyClass:
    def __init__(self) -> None:
        self.value = 42
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_code)
            f.flush()
            temp_path = Path(f.name)

        try:
            violations = [(2, "myrm_agent_server")]
            fixed_count, _ = fix_violations(temp_path, violations)

            assert fixed_count == 1

            fixed_content = temp_path.read_text()

            assert "# BOUNDARY-VIOLATION: from myrm_agent_server import database" in fixed_content
            assert "from typing import Any" in fixed_content
            assert "import myrm_agent_harness" in fixed_content
            assert "def main(x: int) -> str:" in fixed_content
            assert "class MyClass:" in fixed_content
            assert "self.value = 42" in fixed_content

            tree = ast.parse(fixed_content)
            assert any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in ast.walk(tree))
            assert any(isinstance(node, ast.ClassDef) and node.name == "MyClass" for node in ast.walk(tree))
        finally:
            temp_path.unlink()
