"""Progressive content density ladder and peek/skim token throttler.

Implements MFS 4-tier content density ladder (peek, skim, range, full),
AST/regex structural outline extraction, and lazy object safeguards against token blowups.
"""

from __future__ import annotations

import ast
import logging
import re

from myrm_agent_harness.runtime.context.content_density_ladder_types import (
    DensityLevel,
    DensityOutlineNode,
    DensityReadingRequest,
    DensityReadingResult,
)

logger = logging.getLogger(__name__)


class ContentDensityLadderThrottler:
    """Throttles and compresses file content according to the 4-tier density ladder."""

    def read_with_density(
        self,
        content: str,
        request: DensityReadingRequest,
    ) -> DensityReadingResult:
        """Process content according to requested density level and safety limits."""
        raw_bytes = content.encode("utf-8")
        total_bytes = len(raw_bytes)
        lines = content.splitlines()
        total_lines = len(lines)

        # 1. Level 4: FULL with Lazy Object Safeguard
        if request.level == DensityLevel.FULL:
            if total_bytes > request.max_full_size_bytes:
                reason = (
                    f"Full cat refused: file size ({total_bytes} bytes) exceeds safe limit "
                    f"({request.max_full_size_bytes} bytes). Use --peek, --skim, or --range [start:end]."
                )
                logger.warning("Refused full read of oversized file %s: %s", request.file_path, reason)
                return DensityReadingResult(
                    file_path=request.file_path,
                    level=DensityLevel.FULL,
                    rendered_content="",
                    token_count_estimate=0,
                    total_file_lines=total_lines,
                    total_file_bytes=total_bytes,
                    savings_ratio=1.0,
                    is_refused=True,
                    refusal_reason=reason,
                )

            rendered = content
            tokens = self._estimate_tokens(rendered)
            return DensityReadingResult(
                file_path=request.file_path,
                level=DensityLevel.FULL,
                rendered_content=rendered,
                token_count_estimate=tokens,
                total_file_lines=total_lines,
                total_file_bytes=total_bytes,
                savings_ratio=0.0,
                is_refused=False,
            )

        # 2. Level 3: RANGE precise slice
        if request.level == DensityLevel.RANGE:
            start_idx = max(1, request.range_start if request.range_start is not None else 1)
            end_idx = min(total_lines, request.range_end if request.range_end is not None else total_lines)

            if total_lines == 0:
                sliced_lines: list[str] = []
            else:
                sliced_lines = lines[start_idx - 1 : end_idx]

            formatted_slice: list[str] = [
                f"[File: {request.file_path} | Lines {start_idx}-{end_idx} of {total_lines}]"
            ]
            for idx, line in enumerate(sliced_lines, start=start_idx):
                formatted_slice.append(f"{idx:4d} | {line}")

            rendered = "\n".join(formatted_slice)
            savings = max(0.0, 1.0 - (len(rendered) / max(1, len(content))))
            tokens = self._estimate_tokens(rendered)

            return DensityReadingResult(
                file_path=request.file_path,
                level=DensityLevel.RANGE,
                rendered_content=rendered,
                token_count_estimate=tokens,
                total_file_lines=total_lines,
                total_file_bytes=total_bytes,
                savings_ratio=round(savings, 3),
                is_refused=False,
            )

        # 3. Level 1 (PEEK) & Level 2 (SKIM): Extract structural outline
        nodes = self._extract_outline(content, request.file_path)
        rendered_lines: list[str] = [
            f"[File Outline: {request.file_path} | Mode: {request.level.value.upper()} | Total Lines: {total_lines}]"
        ]

        if not nodes:
            rendered_lines.append("  (No structural symbols or section headings detected)")
        else:
            for node in nodes:
                rendered_lines.append(
                    f"  L{node.line_number:4d} [{node.node_type}] {node.title_or_symbol}"
                )
                if request.level == DensityLevel.SKIM and node.summary:
                    rendered_lines.append(f"         ↳ Summary: {node.summary}")

        rendered = "\n".join(rendered_lines)
        savings = max(0.0, 1.0 - (len(rendered) / max(1, len(content))))
        tokens = self._estimate_tokens(rendered)

        return DensityReadingResult(
            file_path=request.file_path,
            level=request.level,
            rendered_content=rendered,
            token_count_estimate=tokens,
            total_file_lines=total_lines,
            total_file_bytes=total_bytes,
            savings_ratio=round(savings, 3),
            is_refused=False,
            outline_nodes=nodes,
        )

    def _extract_outline(self, content: str, file_path: str) -> list[DensityOutlineNode]:
        """Extract structural nodes using AST for Python or Regex for Markdown/Text."""
        if file_path.endswith(".py"):
            return self._extract_python_ast(content)
        return self._extract_markdown_or_generic(content)

    def _extract_python_ast(self, content: str) -> list[DensityOutlineNode]:
        """Extract classes and functions with docstrings from Python source code."""
        nodes: list[DensityOutlineNode] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Fallback to regex if file has incomplete or invalid syntax
            return self._extract_python_regex(content)

        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef):
                doc = ast.get_docstring(stmt)
                summary = doc.splitlines()[0].strip() if doc else None
                nodes.append(
                    DensityOutlineNode(
                        title_or_symbol=f"class {stmt.name}",
                        node_type="class",
                        line_number=stmt.lineno,
                        summary=summary,
                    )
                )
                for child in stmt.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        child_doc = ast.get_docstring(child)
                        child_sum = child_doc.splitlines()[0].strip() if child_doc else None
                        prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                        nodes.append(
                            DensityOutlineNode(
                                title_or_symbol=f"{prefix} {child.name}()",
                                node_type="function",
                                line_number=child.lineno,
                                summary=child_sum,
                            )
                        )
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(stmt)
                summary = doc.splitlines()[0].strip() if doc else None
                prefix = "async def" if isinstance(stmt, ast.AsyncFunctionDef) else "def"
                nodes.append(
                    DensityOutlineNode(
                        title_or_symbol=f"{prefix} {stmt.name}()",
                        node_type="function",
                        line_number=stmt.lineno,
                        summary=summary,
                    )
                )
        return nodes

    def _extract_python_regex(self, content: str) -> list[DensityOutlineNode]:
        """Fallback regex outline extractor for Python."""
        nodes: list[DensityOutlineNode] = []
        for line_num, line in enumerate(content.splitlines(), start=1):
            match = re.match(r"^\s*(class|def|async def)\s+([a-zA-Z0-9_]+)", line)
            if match:
                nodes.append(
                    DensityOutlineNode(
                        title_or_symbol=f"{match.group(1)} {match.group(2)}",
                        node_type="class" if match.group(1) == "class" else "function",
                        line_number=line_num,
                    )
                )
        return nodes

    def _extract_markdown_or_generic(self, content: str) -> list[DensityOutlineNode]:
        """Extract markdown headings and initial sentences."""
        nodes: list[DensityOutlineNode] = []
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                level_marks = heading_match.group(1)
                heading_text = heading_match.group(2)
                # Look ahead for first non-empty text line as summary
                summary: str | None = None
                for next_line in lines[idx + 1 : idx + 5]:
                    next_stripped = next_line.strip()
                    if next_stripped and not next_stripped.startswith("#"):
                        summary = next_stripped[:120]
                        break

                nodes.append(
                    DensityOutlineNode(
                        title_or_symbol=f"{level_marks} {heading_text}",
                        node_type="heading",
                        line_number=idx + 1,
                        summary=summary,
                    )
                )
        return nodes

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count conservatively."""
        return max(1, len(text) // 4)
