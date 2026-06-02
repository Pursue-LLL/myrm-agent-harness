"""Tests for AST-based security analysis of Python skill code."""

import pytest

from myrm_agent_harness.backends.skills.scanning.ast_analyzer import (
    AstScanFinding,
    analyze_python_ast,
    is_python_file,
)


class TestIsPythonFile:
    """File extension detection."""

    def test_py_extension(self):
        assert is_python_file("skill.py") is True

    def test_pyw_extension(self):
        assert is_python_file("script.pyw") is True

    def test_pyi_extension(self):
        assert is_python_file("types.pyi") is True

    def test_non_python(self):
        assert is_python_file("readme.md") is False

    def test_path_with_dirs(self):
        assert is_python_file("scripts/helper.py") is True

    def test_empty_string(self):
        assert is_python_file("") is False


class TestAnalyzePythonAst:
    """Core AST analysis behavior."""

    def test_empty_source(self):
        findings = analyze_python_ast("")
        assert findings == []

    def test_whitespace_only(self):
        findings = analyze_python_ast("   \n\n  ")
        assert findings == []

    def test_syntax_error(self):
        findings = analyze_python_ast("def foo(:\n  pass", "bad.py")
        assert len(findings) == 1
        assert findings[0].threat_type == "ast_parse_error"
        assert findings[0].severity == "info"

    def test_clean_code(self):
        source = """
import os
from pathlib import Path

def greet(name: str) -> str:
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(greet("world"))
"""
        findings = analyze_python_ast(source)
        assert findings == []

    def test_eval_with_dynamic_arg(self):
        source = 'result = eval(user_input)'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "code_injection" and f.severity == "critical" for f in findings)

    def test_eval_with_literal(self):
        source = 'result = eval("1 + 2")'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "code_injection" and f.severity == "high" for f in findings)

    def test_exec_with_dynamic_arg(self):
        source = 'exec(code_string)'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "code_injection" and f.severity == "critical" for f in findings)

    def test_os_system(self):
        source = 'os.system("ls -la")'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "command_injection" and f.severity == "critical" for f in findings)

    def test_subprocess_shell_true(self):
        source = 'subprocess.run("ls", shell=True)'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "command_injection" and "shell=True" in f.description for f in findings)

    def test_subprocess_shell_false(self):
        source = 'subprocess.run(["ls", "-la"])'
        findings = analyze_python_ast(source)
        # No shell=True finding
        assert not any("shell=True" in f.description for f in findings)

    def test_subprocess_dynamic_args(self):
        source = 'subprocess.run(user_command)'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "command_injection" and f.severity == "high" for f in findings)

    def test_pickle_loads(self):
        source = 'data = pickle.loads(raw_bytes)'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "deserialization" and "pickle.loads" in f.description for f in findings)

    def test_yaml_load_unsafe(self):
        source = 'data = yaml.load(content)'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "deserialization" and "SafeLoader" in f.description for f in findings)

    def test_yaml_load_safe(self):
        source = 'data = yaml.load(content, Loader=yaml.SafeLoader)'
        findings = analyze_python_ast(source)
        assert not any(f.threat_type == "deserialization" for f in findings)

    def test_yaml_full_load(self):
        source = 'data = yaml.full_load(content)'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "deserialization" and "full_load" in f.description for f in findings)

    def test_getattr_dynamic(self):
        source = 'value = getattr(obj, attr_name)'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "reflection" and f.severity == "medium" for f in findings)

    def test_getattr_literal(self):
        source = 'value = getattr(obj, "name")'
        findings = analyze_python_ast(source)
        assert not any(f.threat_type == "reflection" for f in findings)

    def test_globals_call(self):
        source = 'ns = globals()'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "reflection" and "globals" in f.description for f in findings)

    def test_locals_call(self):
        source = 'ns = locals()'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "reflection" and "locals" in f.description for f in findings)

    def test_import_dangerous_module(self):
        source = 'import ctypes'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "dangerous_import" and "ctypes" in f.description for f in findings)

    def test_from_import_dangerous(self):
        source = 'from ctypes import CDLL'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "dangerous_import" and "ctypes" in f.description for f in findings)

    def test_dynamic_import(self):
        source = '__import__(module_name)'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "reflection" and "__import__" in f.description for f in findings)

    def test_compile_dynamic(self):
        source = 'code = compile(source_str, "<string>", "exec")'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "code_injection" and "compile" in f.description for f in findings)

    def test_open_write_mode(self):
        source = 'f = open("file.txt", "w")'
        findings = analyze_python_ast(source)
        assert any(f.threat_type == "filesystem_access" and "w" in f.description for f in findings)

    def test_open_read_mode_no_finding(self):
        source = 'f = open("file.txt", "r")'
        findings = analyze_python_ast(source)
        assert not any(f.threat_type == "filesystem_access" for f in findings)

    def test_multiple_threats(self):
        source = """
import ctypes
result = eval(input())
os.system("rm -rf /")
"""
        findings = analyze_python_ast(source)
        threat_types = {f.threat_type for f in findings}
        assert "code_injection" in threat_types
        assert "command_injection" in threat_types
        assert "dangerous_import" in threat_types

    def test_finding_has_line_number(self):
        source = 'x = eval("1")'
        findings = analyze_python_ast(source)
        assert findings[0].line_number == 1

    def test_multiline_line_numbers(self):
        source = """
x = 1
y = 2
result = eval(user_input)
"""
        findings = analyze_python_ast(source)
        eval_findings = [f for f in findings if f.threat_type == "code_injection"]
        assert eval_findings[0].line_number == 4


class TestAstScanFinding:
    """Dataclass behavior."""

    def test_frozen(self):
        finding = AstScanFinding(
            threat_type="test", severity="high", description="test desc", line_number=1
        )
        with pytest.raises(AttributeError):
            finding.threat_type = "changed"

    def test_default_line_number(self):
        finding = AstScanFinding(threat_type="test", severity="high", description="desc")
        assert finding.line_number is None
