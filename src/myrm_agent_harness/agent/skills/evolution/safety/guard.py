"""Evolution guard - Hard constraints for evolved skills.

[INPUT] Evolved skill content
[OUTPUT] GuardResult
[POS] myrm_agent_harness/agent/skills/evolution/guard.py

## Architecture

Pure logic-based hard constraints to prevent destructive AI modifications:
1. AST Signature Check: Ensures function signatures (args, returns) remain intact.
2. Length Penalty: Rejects code that balloons beyond 120% of original size.
3. Absolute Size Limit: Rejects content exceeding MAX_SKILL_CONTENT_CHARS (defense-in-depth).
"""

import ast
from dataclasses import dataclass
from typing import Any

MAX_SKILL_CONTENT_CHARS = 65_536


@dataclass
class GuardResult:
    """Result of evolution guard validation."""

    passed: bool
    reason: str


class EvolutionGuard:
    """Validates evolved skill code against hard constraints."""

    def __init__(self, max_growth_ratio: float = 1.2):
        """Initialize guard.

        Args:
            max_growth_ratio: Maximum allowed growth ratio (e.g., 1.2 = 120% of original size)
        """
        self.max_growth_ratio = max_growth_ratio

    def validate(self, original_content: str, evolved_content: str) -> GuardResult:
        """Run all guard checks.

        Args:
            original_content: Original skill source code
            evolved_content: Evolved skill source code

        Returns:
            GuardResult indicating pass/fail and reason
        """
        # 1. Length Check
        length_result = self._check_length(original_content, evolved_content)
        if not length_result.passed:
            return length_result

        # 2. AST Signature Check
        ast_result = self._check_ast_signatures(original_content, evolved_content)
        if not ast_result.passed:
            return ast_result

        return GuardResult(passed=True, reason="All guard checks passed")

    def _check_length(self, original: str, evolved: str) -> GuardResult:
        """Check if evolved code exceeds growth limits."""
        evolved_len = len(evolved)

        if evolved_len > MAX_SKILL_CONTENT_CHARS:
            return GuardResult(
                passed=False,
                reason=f"Content exceeds absolute size limit: {evolved_len} chars > {MAX_SKILL_CONTENT_CHARS}",
            )

        orig_len = len(original)
        if orig_len == 0:
            return GuardResult(passed=True, reason="Original is empty, within absolute limit")

        ratio = evolved_len / orig_len
        if ratio > self.max_growth_ratio:
            return GuardResult(
                passed=False, reason=f"Code length exceeded limit: {ratio:.1f}x > {self.max_growth_ratio}x"
            )

        return GuardResult(passed=True, reason="Length check passed")

    def _check_ast_signatures(self, original: str, evolved: str) -> GuardResult:
        """Compare AST function signatures to ensure they haven't changed."""
        try:
            orig_ast = ast.parse(original)
            evolved_ast = ast.parse(evolved)
        except SyntaxError as e:
            return GuardResult(passed=False, reason=f"Evolved code has syntax error: {e}")

        orig_funcs = self._extract_function_signatures(orig_ast)
        evolved_funcs = self._extract_function_signatures(evolved_ast)

        # Check if any original function was removed or its signature changed
        for name, orig_sig in orig_funcs.items():
            if name not in evolved_funcs:
                return GuardResult(passed=False, reason=f"Function '{name}' was removed")

            evolved_sig = evolved_funcs[name]
            if orig_sig != evolved_sig:
                return GuardResult(
                    passed=False, reason=f"Function '{name}' signature changed from {orig_sig} to {evolved_sig}"
                )

        return GuardResult(passed=True, reason="AST signature check passed")

    def _extract_function_signatures(self, tree: ast.AST) -> dict[str, dict[str, Any]]:
        """Extract function names and their arguments/returns from AST."""
        funcs = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Extract args
                args = [arg.arg for arg in node.args.args]
                if node.args.vararg:
                    args.append(f"*{node.args.vararg.arg}")
                if node.args.kwarg:
                    args.append(f"**{node.args.kwarg.arg}")

                # Extract return annotation (simple string representation)
                returns = None
                if node.returns:
                    if isinstance(node.returns, ast.Name):
                        returns = node.returns.id
                    elif isinstance(node.returns, ast.Constant):
                        returns = str(node.returns.value)
                    else:
                        returns = "complex_type"  # Simplified for now

                funcs[node.name] = {"args": args, "returns": returns}
        return funcs
