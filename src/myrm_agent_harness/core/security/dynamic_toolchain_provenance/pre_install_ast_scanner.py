"""
[POS] src/myrm_agent_harness/core/security/dynamic_toolchain_provenance/pre_install_ast_scanner.py
[INPUT] ast, logging, typing, .types
[OUTPUT] PreInstallASTScanner

Pre-installation static AST hardening scanner.
Analyzes extension Python source code before sandbox mounting to detect backdoor hooks,
dangerous dynamic execution, undeclared raw sockets, and env credential probes.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import ast
import logging

from .types import ASTScanFinding, ASTViolationType

logger = logging.getLogger(__name__)


class PreInstallASTScanner:
    """Static AST inspector vetting untrusted Python source code prior to installation."""

    DANGEROUS_CALLS: tuple[str, ...] = ("eval", "exec", "compile", "__import__")
    PROCESS_SPAWN_MODULES: tuple[str, ...] = ("subprocess", "pty")
    PROCESS_SPAWN_OS_ATTRS: tuple[str, ...] = ("system", "popen", "spawnl", "spawnv", "execl", "execv")
    SENSITIVE_ENV_KEYWORDS: tuple[str, ...] = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL")

    def scan_source_code(self, source_code: str, skill_id: str = "") -> list[ASTScanFinding]:
        """Parse and inspect Python code AST for unsafe execution patterns."""
        findings: list[ASTScanFinding] = []

        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            findings.append(
                ASTScanFinding(
                    violation_type=ASTViolationType.SYNTAX_ERROR,
                    symbol_name="syntax_error",
                    line_number=exc.lineno or 0,
                    detail=f"Source code fails to parse: {exc.msg}",
                )
            )
            return findings

        for node in ast.walk(tree):
            # 1. Check Function Calls (eval, exec, __import__, compile, os.system, subprocess)
            if isinstance(node, ast.Call):
                self._check_call_node(node, findings)

            # 2. Check Attribute Access (os.environ, socket)
            elif isinstance(node, ast.Attribute):
                self._check_attribute_node(node, findings)

            # 3. Check Subscript (e.g., os.environ['API_KEY'])
            elif isinstance(node, ast.Subscript):
                self._check_subscript_node(node, findings)

        if findings:
            logger.warning(
                "Pre-install AST scan detected %d violations in skill '%s'",
                len(findings),
                skill_id or "unknown",
            )
        else:
            logger.info("Pre-install AST scan passed clean for skill '%s'", skill_id or "unknown")

        return findings

    def _check_call_node(self, node: ast.Call, findings: list[ASTScanFinding]) -> None:
        lineno = getattr(node, "lineno", 0)

        # Direct name call: eval(...), exec(...)
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in self.DANGEROUS_CALLS:
                findings.append(
                    ASTScanFinding(
                        violation_type=ASTViolationType.DANGEROUS_EXEC,
                        symbol_name=func_name,
                        line_number=lineno,
                        detail=f"Direct call to forbidden execution primitive '{func_name}'.",
                    )
                )

        # Attribute call: os.system(...), subprocess.run(...)
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            module_name = self._resolve_name(node.func.value)

            if module_name == "os" and attr_name in self.PROCESS_SPAWN_OS_ATTRS:
                findings.append(
                    ASTScanFinding(
                        violation_type=ASTViolationType.PROCESS_SPAWN,
                        symbol_name=f"os.{attr_name}",
                        line_number=lineno,
                        detail=f"Execution of external shell process via 'os.{attr_name}'.",
                    )
                )
            elif module_name in self.PROCESS_SPAWN_MODULES:
                findings.append(
                    ASTScanFinding(
                        violation_type=ASTViolationType.PROCESS_SPAWN,
                        symbol_name=f"{module_name}.{attr_name}",
                        line_number=lineno,
                        detail=f"Spawning child subprocess via '{module_name}.{attr_name}'.",
                    )
                )
            elif module_name == "socket" and attr_name in ("socket", "create_connection"):
                findings.append(
                    ASTScanFinding(
                        violation_type=ASTViolationType.UNDECLARED_SOCKET,
                        symbol_name=f"socket.{attr_name}",
                        line_number=lineno,
                        detail=f"Raw network socket initialization detected ('socket.{attr_name}').",
                    )
                )

    def _check_attribute_node(self, node: ast.Attribute, findings: list[ASTScanFinding]) -> None:
        lineno = getattr(node, "lineno", 0)
        module_name = self._resolve_name(node.value)

        # os.environ access
        if module_name == "os" and node.attr == "environ":
            findings.append(
                ASTScanFinding(
                    violation_type=ASTViolationType.ENV_CREDENTIAL_PROBE,
                    symbol_name="os.environ",
                    line_number=lineno,
                    detail="Broad environment variable dictionary access via 'os.environ'.",
                )
            )

    def _check_subscript_node(self, node: ast.Subscript, findings: list[ASTScanFinding]) -> None:
        lineno = getattr(node, "lineno", 0)
        # Check if subscripting os.environ with sensitive token
        if (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "environ"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            key = node.slice.value.upper()
            if any(kw in key for kw in self.SENSITIVE_ENV_KEYWORDS):
                findings.append(
                    ASTScanFinding(
                        violation_type=ASTViolationType.ENV_CREDENTIAL_PROBE,
                        symbol_name=f"os.environ['{node.slice.value}']",
                        line_number=lineno,
                        detail=f"Direct attempt to probe sensitive environment credential '{node.slice.value}'.",
                    )
                )

    @staticmethod
    def _resolve_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""
