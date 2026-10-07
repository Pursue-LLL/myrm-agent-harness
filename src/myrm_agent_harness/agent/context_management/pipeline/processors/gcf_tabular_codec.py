"""Pure algorithmic lossless GCF (Grid-Column Format) codec with flattening and bridge support.

[INPUT]
- agent.context_management.pipeline.processors.gcf_tabular_types::GcfColumnarTable, GcfCompressionGuardConfig,
  GcfCompressionResult (POS: Types and models for gcf tabular.)

[OUTPUT]
- GcfTabularCodec: Pure algorithmic lossless GCF (Grid-Column Format) codec with flattening and bridge
  support.

[POS]
Pure algorithmic lossless GCF (Grid-Column Format) codec with flattening and bridge support.
"""

from __future__ import annotations

import csv
import io
import json
import re

from .gcf_tabular_types import (
    GcfColumnarTable,
    GcfCompressionGuardConfig,
    GcfCompressionResult,
)


class GcfTabularCodec:
    """Pure algorithmic lossless GCF (Grid-Column Format) codec with flattening and bridge support."""

    @staticmethod
    def flatten_dict(d: dict[str, object], prefix: str = "") -> dict[str, object]:
        """Flatten nested dictionaries into dot-separated paths (e.g. user.profile.name)."""
        flattened: dict[str, object] = {}
        for key, val in d.items():
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(val, dict):
                flattened.update(GcfTabularCodec.flatten_dict(val, prefix=full_key))
            else:
                flattened[full_key] = val
        return flattened

    @staticmethod
    def unflatten_dict(d: dict[str, object]) -> dict[str, object]:
        """Restore dot-separated flat dictionary back into nested dictionaries."""
        unflattened: dict[str, object] = {}
        for compound_key, val in d.items():
            parts = compound_key.split(".")
            curr = unflattened
            for part in parts[:-1]:
                if part not in curr or not isinstance(curr[part], dict):
                    curr[part] = {}
                curr_next = curr[part]
                assert isinstance(curr_next, dict)
                curr = curr_next
            curr[parts[-1]] = val
        return unflattened

    @classmethod
    def encode_object_array(
        cls,
        objects: list[dict[str, object]],
        config: GcfCompressionGuardConfig | None = None,
    ) -> GcfCompressionResult:
        """Encode an array of row objects into compact columnar GCF representation."""
        cfg = config or GcfCompressionGuardConfig()
        orig_json = json.dumps(objects, ensure_ascii=False)
        orig_chars = len(orig_json)

        # Min rows guard
        if len(objects) < cfg.min_rows:
            return GcfCompressionResult(
                is_compressed=False,
                original_text=orig_json,
                compressed_text=orig_json,
                bypass_reason=f"min_rows_threshold_unmet ({len(objects)} < {cfg.min_rows})",
            )

        # Flatten objects if enabled
        rows_data = [cls.flatten_dict(obj) if cfg.flatten_nested_dot_paths else dict(obj) for obj in objects]

        # Calculate heterogeneity rate
        key_sets = [set(r.keys()) for r in rows_data]
        all_keys = set().union(*key_sets)
        common_keys = set.intersection(*key_sets) if key_sets else set()

        if not all_keys:
            return GcfCompressionResult(
                is_compressed=False,
                original_text=orig_json,
                compressed_text=orig_json,
                bypass_reason="empty_keys_set",
            )

        heterogeneity_rate = 1.0 - (len(common_keys) / len(all_keys))
        if heterogeneity_rate > cfg.max_heterogeneity_rate:
            return GcfCompressionResult(
                is_compressed=False,
                original_text=orig_json,
                compressed_text=orig_json,
                bypass_reason=f"heterogeneity_threshold_exceeded ({heterogeneity_rate:.2f} > {cfg.max_heterogeneity_rate:.2f})",
            )

        # Maintain stable column ordering based on first appearance
        ordered_cols: list[str] = []
        for r in rows_data:
            for k in r:
                if k not in ordered_cols:
                    ordered_cols.append(k)

        # Construct rows
        matrix_rows: list[list[object]] = []
        for r in rows_data:
            row_vals: list[object] = [r.get(col) for col in ordered_cols]
            matrix_rows.append(row_vals)

        table = GcfColumnarTable(cols=ordered_cols, rows=matrix_rows)
        comp_json = table.to_json()
        comp_chars = len(comp_json)
        saved = orig_chars - comp_chars

        if saved < cfg.min_savings_chars:
            return GcfCompressionResult(
                is_compressed=False,
                original_text=orig_json,
                compressed_text=orig_json,
                bypass_reason=f"insufficient_token_savings ({saved} chars < {cfg.min_savings_chars})",
            )

        ratio = saved / orig_chars if orig_chars > 0 else 0.0
        return GcfCompressionResult(
            is_compressed=True,
            original_text=orig_json,
            compressed_text=comp_json,
            cols_count=len(ordered_cols),
            rows_count=len(matrix_rows),
            original_chars=orig_chars,
            compressed_chars=comp_chars,
            compression_ratio=ratio,
            saved_chars=saved,
            table=table,
        )

    @classmethod
    def decode_to_object_array(
        cls,
        table_or_dict: GcfColumnarTable | dict[str, object],
        unflatten_dot_paths: bool = True,
    ) -> list[dict[str, object]]:
        """Decode GCF columnar table back to row-oriented list of object dictionaries (100% lossless)."""
        if isinstance(table_or_dict, GcfColumnarTable):
            cols = table_or_dict.cols
            rows = table_or_dict.rows
        else:
            raw_cols = table_or_dict.get("_cols", [])
            raw_rows = table_or_dict.get("_rows", [])
            assert isinstance(raw_cols, list)
            assert isinstance(raw_rows, list)
            cols = [str(c) for c in raw_cols]
            rows = [list(r) for r in raw_rows]

        restored_rows: list[dict[str, object]] = []
        for row_vals in rows:
            row_dict: dict[str, object] = {}
            for col_idx, col_name in enumerate(cols):
                if col_idx < len(row_vals):
                    row_dict[col_name] = row_vals[col_idx]
                else:
                    row_dict[col_name] = None
            if unflatten_dot_paths and any("." in k for k in row_dict):
                restored_rows.append(cls.unflatten_dict(row_dict))
            else:
                restored_rows.append(row_dict)
        return restored_rows

    @classmethod
    def parse_markdown_table(cls, md_text: str) -> list[dict[str, object]]:
        """Parse GitHub-flavored markdown table into a list of row objects."""
        lines = [line.strip() for line in md_text.strip().splitlines() if line.strip().startswith("|")]
        if len(lines) < 3:
            return []

        # Parse header
        headers = [c.strip() for c in lines[0].strip("|").split("|")]
        # Line 1 is separator |---|---|
        data_rows: list[dict[str, object]] = []
        for line in lines[2:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            row: dict[str, object] = {}
            for idx, h in enumerate(headers):
                val = cells[idx] if idx < len(cells) else ""
                row[h] = val
            data_rows.append(row)
        return data_rows

    @classmethod
    def parse_csv_text(cls, csv_text: str) -> list[dict[str, object]]:
        """Parse raw CSV text into a list of row objects."""
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        return [dict(row) for row in reader]

    @classmethod
    def encode_tabular_text(
        cls,
        text: str,
        config: GcfCompressionGuardConfig | None = None,
    ) -> GcfCompressionResult:
        """Autodetect and bridge Markdown Table or CSV text into GCF representation."""
        trimmed = text.strip()
        # Probe Markdown Table
        if re.search(r"^\|.+\|\s*\n\|[-:| ]+\|\s*\n\|.+\|", trimmed, re.MULTILINE):
            objects = cls.parse_markdown_table(trimmed)
            if objects:
                return cls.encode_object_array(objects, config=config)

        # Probe CSV
        if "," in trimmed and "\n" in trimmed:
            try:
                objects = cls.parse_csv_text(trimmed)
                if objects and len(objects) >= (config.min_rows if config else 3):
                    return cls.encode_object_array(objects, config=config)
            except Exception:
                pass

        return GcfCompressionResult(
            is_compressed=False,
            original_text=text,
            compressed_text=text,
            bypass_reason="unrecognized_tabular_format",
        )
