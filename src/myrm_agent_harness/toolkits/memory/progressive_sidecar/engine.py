"""[POS]: src/myrm_agent_harness/toolkits/memory/progressive_sidecar/engine.py
[INPUT]: Raw text documents, Markdown structures, and doc identifiers.
[OUTPUT]: ProgressiveSidecarEngine generating L0 abstract, L1 overview, and OKF frontmatter bundles.
"""

import hashlib
import re
import time

from .models import (
    OKFFrontmatter,
    ProgressiveContextBundle,
)


class ProgressiveSidecarEngine:
    """Deterministic heuristic generator producing three-tier context sidecars."""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count across multilingual text payloads."""
        if not text:
            return 0
        # Multilingual heuristic: count words + CJK characters
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        non_cjk = re.sub(r"[\u4e00-\u9fff]", "", text)
        words = len(non_cjk.split())
        return max(1, cjk_chars + int(words * 1.3))

    @classmethod
    def extract_l0_abstract(cls, content: str, max_tokens: int = 120) -> str:
        """Synthesize ultra-compact L0 abstract (~100 tokens) for rapid relevance screening."""
        clean = content.strip()
        if not clean:
            return "Empty document."

        lines = [line.strip() for line in clean.splitlines() if line.strip()]
        # Filter out markdown heading markers for body discovery
        candidates: list[str] = []
        for line in lines:
            if line.startswith("#"):
                continue
            if line.startswith("```"):
                continue
            candidates.append(line)

        if not candidates:
            # Fallback to first line
            return lines[0][:200]

        summary_parts: list[str] = []
        accumulated_tokens = 0
        for cand in candidates:
            cand_tokens = cls.estimate_tokens(cand)
            if accumulated_tokens + cand_tokens > max_tokens and summary_parts:
                break
            summary_parts.append(cand)
            accumulated_tokens += cand_tokens
            if accumulated_tokens >= max_tokens:
                break

        abstract_text = " ".join(summary_parts)
        if len(abstract_text) > 400:
            abstract_text = abstract_text[:397] + "..."
        return abstract_text

    @classmethod
    def extract_l1_overview(cls, content: str, max_tokens: int = 2000) -> str:
        """Extract structural outline, headings hierarchy, and key contract definitions for L1 overview."""
        clean = content.strip()
        if not clean:
            return "Empty document structure."

        lines = clean.splitlines()
        overview_lines: list[str] = []
        in_code_block = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                if in_code_block:
                    overview_lines.append(stripped)
                continue

            if in_code_block:
                # Capture key declarations inside code blocks (classes, functions, interfaces)
                if re.match(r"^(class|def|interface|type|async def|func)\b", stripped):
                    overview_lines.append(f"  {stripped}")
                continue

            # Capture markdown headings
            if re.match(r"^#{1,6}\s+", stripped):
                overview_lines.append(stripped)
                continue

            # Capture key bullet points and contract definitions
            if stripped.startswith(("- **", "* **", "1. **", "2. **", "3. **")):
                overview_lines.append(stripped)

        if not overview_lines:
            # Fallback to first 500 characters
            return clean[:500]

        overview_text = "\n".join(overview_lines)
        tokens = cls.estimate_tokens(overview_text)
        if tokens > max_tokens:
            truncated_lines: list[str] = []
            cur_tokens = 0
            for ol in overview_lines:
                t = cls.estimate_tokens(ol)
                if cur_tokens + t > max_tokens:
                    truncated_lines.append("... [additional structural items truncated]")
                    break
                truncated_lines.append(ol)
                cur_tokens += t
            overview_text = "\n".join(truncated_lines)

        return overview_text

    @classmethod
    def generate_bundle(
        cls,
        doc_id: str,
        content: str,
        title: str = "",
    ) -> ProgressiveContextBundle:
        """Generate comprehensive three-tier context bundle with OKF frontmatter."""
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        l0 = cls.extract_l0_abstract(content)
        l1 = cls.extract_l1_overview(content)

        l0_tokens = cls.estimate_tokens(l0)
        l1_tokens = cls.estimate_tokens(l1)
        l2_tokens = cls.estimate_tokens(content)

        savings = 0.0
        if l2_tokens > 0:
            savings = max(0.0, min(100.0, (1.0 - (l0_tokens / l2_tokens)) * 100.0))

        frontmatter = OKFFrontmatter(
            doc_id=doc_id,
            title=title or doc_id.split("/")[-1],
            digest_sha256=digest,
            l0_tokens_est=l0_tokens,
            l1_tokens_est=l1_tokens,
            l2_tokens_est=l2_tokens,
            updated_at_epoch=time.time(),
        )

        return ProgressiveContextBundle(
            doc_id=doc_id,
            frontmatter=frontmatter,
            l0_abstract=l0,
            l1_overview=l1,
            l2_detail=content,
            token_savings_pct=round(savings, 2),
        )
