"""
[POS] src/myrm_agent_harness/core/security/skill_health_audit/ast_taint_engine.py
[INPUT] ast, typing, types
[OUTPUT] SkillTaintSentinelEngine
AST taint sentinel engine identifying undeclared exfiltration flows from sources to network sinks.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import ast
import logging

from .types import (
    SkillSecurityMetadata,
    TaintFlowFinding,
    TaintSeverity,
)

logger = logging.getLogger(__name__)

# Known external network sinks that can transmit exfiltrated data
_NETWORK_SINKS: frozenset[str] = frozenset(
    {
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.delete",
        "requests.request",
        "httpx.get",
        "httpx.post",
        "httpx.put",
        "httpx.delete",
        "httpx.request",
        "urllib.request.urlopen",
        "socket.create_connection",
        "socket.connect",
        "aiohttp.ClientSession",
    }
)

# Dangerous system execution APIs
_DANGEROUS_SYSCALLS: frozenset[str] = frozenset(
    {
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_output",
        "os.system",
        "os.popen",
        "shutil.rmtree",
    }
)


class SkillTaintSentinelEngine:
    """AST analyzer checking for sensitive source-to-sink taint flows and undeclared network exfiltration."""

    @staticmethod
    def _is_sensitive_source(symbol: str) -> bool:
        """Check whether symbol represents a sensitive credential, env or local filesystem source."""
        if not symbol:
            return False
        if symbol.startswith("os.environ") or symbol.startswith("os.getenv"):
            return True
        if symbol in ("open", "dotenv_values", "dotenv.load_dotenv"):
            return True
        return symbol.endswith(".read_text") or symbol.endswith(".read_bytes")

    def analyze_source_code(
        self,
        code: str,
        metadata: SkillSecurityMetadata,
    ) -> tuple[tuple[TaintFlowFinding, ...], int]:
        """Perform AST taint and undeclared exfiltration analysis.

        Returns:
            A tuple of (taint_findings, dangerous_syscalls_count).
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            logger.warning("Failed to parse code for skill %s: %s", metadata.skill_name, e)
            return (
                (
                    TaintFlowFinding(
                        source_type="syntax_error",
                        sink_type="none",
                        line_number=getattr(e, "lineno", 1) or 1,
                        symbol=str(e),
                        is_declared=False,
                        severity=TaintSeverity.WARNING,
                        description=f"Syntax error prevents complete AST analysis: {e}",
                    ),
                ),
                0,
            )

        # Pass 1: Identify all sensitive sources upfront
        has_sensitive_source = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                attr_name = self._resolve_attribute_name(node)
                if self._is_sensitive_source(attr_name):
                    has_sensitive_source = True
            elif isinstance(node, ast.Call):
                call_name = self._resolve_call_name(node.func)
                if self._is_sensitive_source(call_name):
                    has_sensitive_source = True

        findings: list[TaintFlowFinding] = []
        dangerous_syscalls_count = 0

        # Pass 2: Inspect dangerous syscalls and network sinks
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_repr = self._resolve_call_name(node.func)
                lineno = getattr(node, "lineno", 1)

                # Check dangerous syscalls
                if call_repr in _DANGEROUS_SYSCALLS:
                    dangerous_syscalls_count += 1
                    findings.append(
                        TaintFlowFinding(
                            source_type="syscall",
                            sink_type=call_repr,
                            line_number=lineno,
                            symbol=call_repr,
                            is_declared=False,
                            severity=TaintSeverity.HIGH,
                            description=f"Execution of dangerous system call: {call_repr}",
                        )
                    )

                # Check network sinks
                if call_repr in _NETWORK_SINKS:
                    is_declared = self._is_sink_declared(call_repr, metadata)
                    if not is_declared:
                        sev = (
                            TaintSeverity.CRITICAL_BLOCK
                            if has_sensitive_source
                            else TaintSeverity.HIGH
                        )
                        desc = (
                            f"Undeclared network sink '{call_repr}' detected without frontmatter declaration"
                            if not has_sensitive_source
                            else f"Taint leak: sensitive source flow into undeclared network sink '{call_repr}'"
                        )
                        findings.append(
                            TaintFlowFinding(
                                source_type="sensitive_data" if has_sensitive_source else "code",
                                sink_type=call_repr,
                                line_number=lineno,
                                symbol=call_repr,
                                is_declared=False,
                                severity=sev,
                                description=desc,
                            )
                        )
                    else:
                        findings.append(
                            TaintFlowFinding(
                                source_type="code",
                                sink_type=call_repr,
                                line_number=lineno,
                                symbol=call_repr,
                                is_declared=True,
                                severity=TaintSeverity.INFO,
                                description=f"Declared network egress: {call_repr}",
                            )
                        )

        return tuple(findings), dangerous_syscalls_count

    @staticmethod
    def _is_sink_declared(sink_name: str, metadata: SkillSecurityMetadata) -> bool:
        """Check whether the network egress sink is covered by external_requests in metadata."""
        if not metadata.external_requests:
            return False
        return any(len(req.url.strip()) > 0 for req in metadata.external_requests)

    @staticmethod
    def _resolve_call_name(node: ast.expr) -> str:
        """Resolve AST callable node to dot-separated name."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = SkillTaintSentinelEngine._resolve_call_name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    @staticmethod
    def _resolve_attribute_name(node: ast.Attribute) -> str:
        """Resolve AST attribute node to dot-separated name."""
        prefix = SkillTaintSentinelEngine._resolve_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
