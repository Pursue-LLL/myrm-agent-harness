"""Specialized multi-format lossless compaction operators for tool results.

[INPUT]
- pipeline.processors.content_router_types::ToolResultFormatKind, AdaptiveCompactorConfig, AdaptiveCompactionResult
- pipeline.processors.gcf_tabular_codec::GcfTabularCodec
- pipeline.processors.tool_result_content_sniffer::ToolResultContentSniffer

[OUTPUT]
- AdaptiveToolResultCompactor: 多格式自适应无损紧凑化算子矩阵
"""

from __future__ import annotations

import json
import re
from typing import cast

from .content_router_types import (
    AdaptiveCompactionResult,
    AdaptiveCompactorConfig,
    ToolResultFormatKind,
)
from .gcf_tabular_codec import GcfTabularCodec
from .tool_result_content_sniffer import ToolResultContentSniffer


class AdaptiveToolResultCompactor:
    """Multi-format lossless compactor with defensive rollback guards."""

    _GIT_METADATA_LINES_RE = re.compile(
        r"^(index [0-9a-f]+\.\.[0-9a-f]+.*|(?:new|deleted) file mode \d+|similarity index \d+%.*)\n?",
        re.MULTILINE,
    )
    _GREP_LINE_PARSER = re.compile(r"^([^:\s\n]+):(\d+):(.*)$")

    @classmethod
    def compact(
        cls,
        text: str,
        config: AdaptiveCompactorConfig | None = None,
        forced_kind: ToolResultFormatKind | None = None,
    ) -> AdaptiveCompactionResult:
        """Route text to specialized compressor and return diagnostic outcome."""
        cfg = config or AdaptiveCompactorConfig()
        orig_chars = len(text)
        if orig_chars == 0:
            return AdaptiveCompactionResult(
                format_kind=ToolResultFormatKind.PLAIN_TEXT,
                is_compacted=False,
                original_text="",
                compacted_text="",
                bypass_reason="empty_input",
            )

        kind = forced_kind or ToolResultContentSniffer.sniff(text)

        if kind == ToolResultFormatKind.JSON_ARRAY:
            return cls._compact_json_array(text, cfg)
        if kind == ToolResultFormatKind.TABULAR:
            return cls._compact_tabular(text, cfg)
        if kind == ToolResultFormatKind.UNIFIED_DIFF:
            return cls._compact_unified_diff(text, cfg)
        if kind == ToolResultFormatKind.REPEATED_LOGS:
            return cls._compact_repeated_logs(text, cfg)
        if kind == ToolResultFormatKind.GREP_MATCHES:
            return cls._compact_grep_matches(text, cfg)

        return AdaptiveCompactionResult(
            format_kind=ToolResultFormatKind.PLAIN_TEXT,
            is_compacted=False,
            original_text=text,
            compacted_text=text,
            original_chars=orig_chars,
            compacted_chars=orig_chars,
            bypass_reason="plain_text_passthrough",
        )

    @classmethod
    def _compact_json_array(cls, text: str, cfg: AdaptiveCompactorConfig) -> AdaptiveCompactionResult:
        try:
            parsed = json.loads(text.strip())
            if isinstance(parsed, list) and all(isinstance(x, dict) for x in parsed):
                dict_list = cast(list[dict[str, object]], parsed)
                gcf_res = GcfTabularCodec.encode_object_array(dict_list)
                if gcf_res.is_compressed and gcf_res.saved_chars >= cfg.min_savings_chars:
                    return AdaptiveCompactionResult(
                        format_kind=ToolResultFormatKind.JSON_ARRAY,
                        is_compacted=True,
                        original_text=text,
                        compacted_text=gcf_res.compressed_text,
                        original_chars=len(text),
                        compacted_chars=len(gcf_res.compressed_text),
                        saved_chars=gcf_res.saved_chars,
                        compression_ratio=gcf_res.compression_ratio,
                        details={"cols": gcf_res.cols_count, "rows": gcf_res.rows_count},
                    )
        except Exception:
            pass

        return AdaptiveCompactionResult(
            format_kind=ToolResultFormatKind.JSON_ARRAY,
            is_compacted=False,
            original_text=text,
            compacted_text=text,
            original_chars=len(text),
            compacted_chars=len(text),
            bypass_reason="json_array_uncompressible_or_below_savings_threshold",
        )

    @classmethod
    def _compact_tabular(cls, text: str, cfg: AdaptiveCompactorConfig) -> AdaptiveCompactionResult:
        tab_res = GcfTabularCodec.encode_tabular_text(text)
        if tab_res.is_compressed and tab_res.saved_chars >= cfg.min_savings_chars:
            return AdaptiveCompactionResult(
                format_kind=ToolResultFormatKind.TABULAR,
                is_compacted=True,
                original_text=text,
                compacted_text=tab_res.compressed_text,
                original_chars=len(text),
                compacted_chars=len(tab_res.compressed_text),
                saved_chars=tab_res.saved_chars,
                compression_ratio=tab_res.compression_ratio,
                details={"cols": tab_res.cols_count, "rows": tab_res.rows_count},
            )

        return AdaptiveCompactionResult(
            format_kind=ToolResultFormatKind.TABULAR,
            is_compacted=False,
            original_text=text,
            compacted_text=text,
            original_chars=len(text),
            compacted_chars=len(text),
            bypass_reason="tabular_uncompressible_or_below_savings_threshold",
        )

    @classmethod
    def _compact_unified_diff(cls, text: str, cfg: AdaptiveCompactorConfig) -> AdaptiveCompactionResult:
        orig_chars = len(text)
        if not cfg.strip_diff_metadata:
            return AdaptiveCompactionResult(
                format_kind=ToolResultFormatKind.UNIFIED_DIFF,
                is_compacted=False,
                original_text=text,
                compacted_text=text,
                bypass_reason="diff_metadata_strip_disabled",
            )

        cleaned = cls._GIT_METADATA_LINES_RE.sub("", text)
        saved = orig_chars - len(cleaned)
        if saved >= cfg.min_savings_chars:
            return AdaptiveCompactionResult(
                format_kind=ToolResultFormatKind.UNIFIED_DIFF,
                is_compacted=True,
                original_text=text,
                compacted_text=cleaned,
                original_chars=orig_chars,
                compacted_chars=len(cleaned),
                saved_chars=saved,
                compression_ratio=saved / orig_chars if orig_chars > 0 else 0.0,
            )

        return AdaptiveCompactionResult(
            format_kind=ToolResultFormatKind.UNIFIED_DIFF,
            is_compacted=False,
            original_text=text,
            compacted_text=text,
            original_chars=orig_chars,
            compacted_chars=orig_chars,
            bypass_reason="diff_savings_below_threshold",
        )

    @classmethod
    def _compact_repeated_logs(cls, text: str, cfg: AdaptiveCompactorConfig) -> AdaptiveCompactionResult:
        orig_chars = len(text)
        lines = text.splitlines(keepends=True)
        if len(lines) < 2:
            return AdaptiveCompactionResult(
                format_kind=ToolResultFormatKind.REPEATED_LOGS,
                is_compacted=False,
                original_text=text,
                compacted_text=text,
                bypass_reason="too_few_log_lines",
            )

        compacted_lines: list[str] = []
        i = 0
        total_folded_runs = 0

        while i < len(lines):
            curr_line = lines[i]
            run_len = 1
            while (i + run_len) < len(lines) and lines[i + run_len] == curr_line:
                run_len += 1

            if run_len >= cfg.min_log_repeat_count:
                eol = "\n" if curr_line.endswith("\n") else ""
                clean_content = curr_line.rstrip("\r\n")
                folded_entry = f"[repeated {run_len} times]: {clean_content}{eol}"
                compacted_lines.append(folded_entry)
                total_folded_runs += 1
                i += run_len
            else:
                compacted_lines.append(curr_line)
                i += 1

        compacted_text = "".join(compacted_lines)
        saved = orig_chars - len(compacted_text)

        if total_folded_runs > 0 and saved >= cfg.min_savings_chars:
            return AdaptiveCompactionResult(
                format_kind=ToolResultFormatKind.REPEATED_LOGS,
                is_compacted=True,
                original_text=text,
                compacted_text=compacted_text,
                original_chars=orig_chars,
                compacted_chars=len(compacted_text),
                saved_chars=saved,
                compression_ratio=saved / orig_chars if orig_chars > 0 else 0.0,
                details={"folded_runs": total_folded_runs},
            )

        return AdaptiveCompactionResult(
            format_kind=ToolResultFormatKind.REPEATED_LOGS,
            is_compacted=False,
            original_text=text,
            compacted_text=text,
            original_chars=orig_chars,
            compacted_chars=orig_chars,
            bypass_reason="no_repeated_logs_or_insufficient_savings",
        )

    @classmethod
    def _compact_grep_matches(cls, text: str, cfg: AdaptiveCompactorConfig) -> AdaptiveCompactionResult:
        orig_chars = len(text)
        if not cfg.enable_grep_path_grouping:
            return AdaptiveCompactionResult(
                format_kind=ToolResultFormatKind.GREP_MATCHES,
                is_compacted=False,
                original_text=text,
                compacted_text=text,
                bypass_reason="grep_path_grouping_disabled",
            )

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < cfg.min_grep_lines_to_group:
            return AdaptiveCompactionResult(
                format_kind=ToolResultFormatKind.GREP_MATCHES,
                is_compacted=False,
                original_text=text,
                compacted_text=text,
                bypass_reason="too_few_grep_lines",
            )

        grouped: dict[str, list[tuple[str, str]]] = {}
        for line in lines:
            match = cls._GREP_LINE_PARSER.match(line)
            if match:
                path, lineno, code = match.group(1), match.group(2), match.group(3)
                grouped.setdefault(path, []).append((lineno, code))
            else:
                grouped.setdefault("", []).append(("", line))

        output_lines: list[str] = []
        for path, entries in grouped.items():
            if path:
                output_lines.append(f"{path}:")
                for lineno, code in entries:
                    output_lines.append(f"  L{lineno}: {code.strip()}")
            else:
                for _, raw in entries:
                    output_lines.append(raw)

        compacted_text = "\n".join(output_lines)
        saved = orig_chars - len(compacted_text)

        if saved >= cfg.min_savings_chars:
            return AdaptiveCompactionResult(
                format_kind=ToolResultFormatKind.GREP_MATCHES,
                is_compacted=True,
                original_text=text,
                compacted_text=compacted_text,
                original_chars=orig_chars,
                compacted_chars=len(compacted_text),
                saved_chars=saved,
                compression_ratio=saved / orig_chars if orig_chars > 0 else 0.0,
                details={"grouped_files": len(grouped)},
            )

        return AdaptiveCompactionResult(
            format_kind=ToolResultFormatKind.GREP_MATCHES,
            is_compacted=False,
            original_text=text,
            compacted_text=text,
            original_chars=orig_chars,
            compacted_chars=orig_chars,
            bypass_reason="grep_savings_below_threshold",
        )
