"""Scoped CSS AST Rewriter and Global Selector Invariant Enforcement."""

from __future__ import annotations

import re

from .types import (
    CssScopingResult,
    CssViolationSeverity,
    GlobalSelectorViolation,
)

_GLOBAL_FORBIDDEN_ROOTS: frozenset[str] = frozenset({
    "html",
    "body",
    ":root",
    "*",
    "head",
})

_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)


class ScopedCssAstRewriter:
    """Parses CSS styles and wraps selectors with component scopes while barring global root selectors."""

    def scope_css(self, css_content: str, scope_id: str) -> CssScopingResult:
        """Enforce scoped containment on CSS content by prefixing component scope selector.

        Rejects styles that introduce global root pollution (e.g. 'html', 'body', ':root', '*').
        """
        clean_scope = self._normalize_scope_prefix(scope_id)
        stripped_content = _COMMENT_PATTERN.sub("", css_content).strip()

        violations: list[GlobalSelectorViolation] = []
        rewritten_blocks: list[str] = []
        rules_rewritten = 0

        # Parse rule blocks at top level
        blocks = self._extract_css_blocks(stripped_content)

        for prelude, body in blocks:
            prelude = prelude.strip()
            body = body.strip()

            if not prelude:
                continue

            # Handle @media queries
            if prelude.lower().startswith("@media"):
                inner_blocks = self._extract_css_blocks(body)
                inner_rewritten: list[str] = []
                for inner_prelude, inner_body in inner_blocks:
                    res_inner = self._scope_standard_rule(inner_prelude, inner_body, clean_scope)
                    if res_inner[1]:
                        violations.extend(res_inner[1])
                    if res_inner[0]:
                        inner_rewritten.append(res_inner[0])
                        rules_rewritten += 1

                if inner_rewritten:
                    joined_inner = "\n  ".join(inner_rewritten)
                    rewritten_blocks.append(f"{prelude} {{\n  {joined_inner}\n}}")
                continue

            # Handle standard CSS rule block
            rule_str, rule_violations = self._scope_standard_rule(prelude, body, clean_scope)
            if rule_violations:
                violations.extend(rule_violations)
            if rule_str:
                rewritten_blocks.append(rule_str)
                rules_rewritten += 1

        is_valid = len([v for v in violations if v.severity == CssViolationSeverity.CRITICAL_REJECTION]) == 0
        final_css = "\n\n".join(rewritten_blocks) if is_valid else ""

        return CssScopingResult(
            is_valid=is_valid,
            original_css=css_content,
            scoped_css=final_css,
            scope_id=clean_scope,
            violations=violations,
            rules_rewritten=rules_rewritten if is_valid else 0,
        )

    def _scope_standard_rule(
        self,
        selectors_str: str,
        body: str,
        scope_prefix: str,
    ) -> tuple[str | None, list[GlobalSelectorViolation]]:
        """Validate and rewrite standard selector list."""
        violations: list[GlobalSelectorViolation] = []
        scoped_selectors: list[str] = []

        raw_selectors = [s.strip() for s in selectors_str.split(",") if s.strip()]

        for sel in raw_selectors:
            # Check for forbidden global root selectors
            tokens = [t for t in re.split(r"[\s>+~]", sel.strip()) if t]
            first_token = tokens[0].lower() if tokens else ""
            is_forbidden = (
                first_token in _GLOBAL_FORBIDDEN_ROOTS
                or first_token.startswith(":root")
                or any(
                    first_token.startswith(root)
                    and (len(first_token) == len(root) or first_token[len(root)] in (".", "#", ":", "["))
                    for root in ("html", "body", "head")
                )
            )
            if is_forbidden:
                violations.append(
                    GlobalSelectorViolation(
                        selector=sel,
                        reason=(
                            f"Violation of Scoped CSS Invariant: global root selector '{sel}' detected. "
                            f"Micro-agents must confine styles inside target scope '{scope_prefix}'."
                        ),
                        severity=CssViolationSeverity.CRITICAL_REJECTION,
                    )
                )
                continue

            # Prefix with scope container
            if sel.startswith("&"):
                scoped_selectors.append(f"{scope_prefix}{sel[1:]}")
            else:
                scoped_selectors.append(f"{scope_prefix} {sel}")

        if violations:
            return None, violations

        joined_selectors = ", ".join(scoped_selectors)
        clean_body = body.strip().rstrip(";")
        formatted_body = ";\n  ".join([line.strip() for line in clean_body.split(";") if line.strip()])
        return f"{joined_selectors} {{\n  {formatted_body};\n}}", []

    @staticmethod
    def _normalize_scope_prefix(scope_id: str) -> str:
        """Ensure scope prefix is a valid CSS id or class selector."""
        trimmed = scope_id.strip()
        if not trimmed.startswith(("#", ".")):
            return f"#{trimmed}"
        return trimmed

    @staticmethod
    def _extract_css_blocks(content: str) -> list[tuple[str, str]]:
        """Extract top-level (prelude, body) tuples using brace matching."""
        blocks: list[tuple[str, str]] = []
        i = 0
        n = len(content)

        while i < n:
            brace_open = content.find("{", i)
            if brace_open == -1:
                break

            prelude = content[i:brace_open].strip()
            depth = 1
            j = brace_open + 1

            while j < n and depth > 0:
                if content[j] == "{":
                    depth += 1
                elif content[j] == "}":
                    depth -= 1
                j += 1

            body = content[brace_open + 1 : j - 1]
            blocks.append((prelude, body))
            i = j

        return blocks
