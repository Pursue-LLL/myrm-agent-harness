"""[INPUT]
- models: DelightCategory, DelightTemplate, SingleFileSandboxContract, SandboxValidationResult

[OUTPUT]
- SingleFileSandboxEngine: Core engine validating and compiling self-contained delight artifacts

[POS]
Harness framework layer engine for Zero-Code Hobbyist Delight & Single-File Sandbox (Item 40 P0).
Strictly under 160 lines. Zero `Any`.
"""

from __future__ import annotations

import re
import uuid
from typing import ClassVar

from .models import (
    SandboxValidationResult,
    SingleFileSandboxContract,
)


class SingleFileSandboxEngine:
    """Validates and compiles single-file self-contained HTML5/Canvas delight artifacts."""

    CANVAS_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"<canvas\b", re.IGNORECASE)
    AUDIO_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(AudioContext|webkitAudioContext|<audio\b)", re.IGNORECASE
    )
    TAILWIND_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(tailwindcss|cdn\.tailwindcss\.com|class=[\"'][^\"']*\b(flex|grid|p-|m-|text-|bg-))",
        re.IGNORECASE,
    )
    EXTERNAL_BUNDLE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"""(import\s+.*?from\s+['"](?!\bhttps?:\/\/)[^'"]+['"]|require\s*\(\s*['"](?!\bhttps?:\/\/)[^'"]+['"]\))""",
        re.IGNORECASE,
    )

    MOBILE_VIEWPORT_TAG: ClassVar[str] = (
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, '
        'maximum-scale=1.0, user-scalable=no, viewport-fit=cover">'
    )

    BASE_FULLSCREEN_STYLE: ClassVar[str] = (
        "<style>"
        "html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;box-sizing:border-box;}"
        "*{box-sizing:border-box;}"
        "</style>"
    )

    def validate_and_compile(self, html_source: str, title: str = "Delight Sandbox") -> SandboxValidationResult:
        """Inspects HTML source code for self-containment and compiles it with viewport/safety guards."""
        raw = html_source.strip()
        issues: list[str] = []

        if not raw:
            return SandboxValidationResult(
                is_valid=False,
                issues=["HTML content cannot be empty"],
                has_canvas=False,
                has_audio=False,
                has_tailwind=False,
                compiled_html="",
            )

        # 1. Detect relative external imports that would break in single-file sandbox
        if self.EXTERNAL_BUNDLE_PATTERN.search(raw):
            issues.append("Disallowed relative import/require found; must be purely self-contained or standard CDN")

        has_canvas = bool(self.CANVAS_PATTERN.search(raw))
        has_audio = bool(self.AUDIO_PATTERN.search(raw))
        has_tailwind = bool(self.TAILWIND_PATTERN.search(raw))

        # 2. Normalize full HTML structure
        compiled = raw
        if "<!DOCTYPE html>" not in compiled and "<html" not in compiled.lower():
            # Wrap partial body / canvas fragment into complete document
            compiled = (
                "<!DOCTYPE html>\n"
                '<html lang="en">\n'
                "<head>\n"
                '  <meta charset="UTF-8">\n'
                f"  {self.MOBILE_VIEWPORT_TAG}\n"
                f"  <title>{title}</title>\n"
                f"  {self.BASE_FULLSCREEN_STYLE}\n"
                '  <script src="https://cdn.tailwindcss.com"></script>\n'
                "</head>\n"
                "<body>\n"
                f"{raw}\n"
                "</body>\n"
                "</html>"
            )
        else:
            # Ensure mobile viewport meta is injected if missing
            if "viewport" not in compiled.lower():
                if "<head>" in compiled:
                    compiled = compiled.replace("<head>", f"<head>\n  {self.MOBILE_VIEWPORT_TAG}")
                elif "<head " in compiled:
                    compiled = re.sub(r"(<head\b[^>]*>)", rf"\1\n  {self.MOBILE_VIEWPORT_TAG}", compiled, count=1)

            # Ensure reset fullscreen styles are present
            if self.BASE_FULLSCREEN_STYLE not in compiled and "</head>" in compiled:
                compiled = compiled.replace("</head>", f"  {self.BASE_FULLSCREEN_STYLE}\n</head>")

        return SandboxValidationResult(
            is_valid=len(issues) == 0,
            issues=issues,
            has_canvas=has_canvas,
            has_audio=has_audio,
            has_tailwind=has_tailwind,
            compiled_html=compiled,
        )

    def create_contract(
        self,
        session_id: str,
        title: str,
        html_source: str,
    ) -> SingleFileSandboxContract:
        """Produces a verified SingleFileSandboxContract ready for instant sandboxed execution."""
        val = self.validate_and_compile(html_source, title=title)
        return SingleFileSandboxContract(
            contract_id=f"sc_{uuid.uuid4().hex[:10]}",
            session_id=session_id,
            title=title,
            html_content=html_source,
            has_canvas=val.has_canvas,
            has_audio=val.has_audio,
            has_tailwind=val.has_tailwind,
            is_self_contained=val.is_valid,
            compiled_html=val.compiled_html,
        )
