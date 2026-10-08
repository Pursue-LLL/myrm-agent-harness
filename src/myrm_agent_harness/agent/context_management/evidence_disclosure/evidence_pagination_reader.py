"""Pagination reader binding evidence viewing to verified real-reading offsets.

[INPUT]
- ActionDetailDescriptor: Unified canonical descriptor of an action.
- PaginatedEvidencePage: Paginated container with real-read metadata.
- RealReadSlice: Content slice bound to deterministic offsets and sha256 checksum.

[OUTPUT]
- BoundedEvidenceReader: Engine calculating pagination windows bound to verifiable reading offsets.

[POS]
Evidence pagination and bounded real-reading offset verification engine.
"""

from __future__ import annotations

import hashlib
import math
from typing import Mapping, Sequence

from .evidence_disclosure_types import (
    ActionDetailDescriptor,
    PaginatedEvidencePage,
    RealReadSlice,
)


class BoundedEvidenceReader:
    """Bounded pagination reader coupling evidence presentation to deterministic reading offsets."""

    def __init__(self, default_page_size: int = 10, max_page_size: int = 100) -> None:
        if default_page_size <= 0:
            raise ValueError(f"default_page_size must be positive, got {default_page_size}")
        if max_page_size < default_page_size:
            raise ValueError(f"max_page_size {max_page_size} cannot be less than default {default_page_size}")
        self._default_page_size = default_page_size
        self._max_page_size = max_page_size

    def paginate_and_read(
        self,
        descriptors: Sequence[ActionDetailDescriptor],
        *,
        page_number: int = 1,
        page_size: int | None = None,
        text_content_by_ref: Mapping[str, str] | None = None,
        max_text_window: int = 512,
    ) -> PaginatedEvidencePage:
        """Paginate action descriptors and bind each item to verifiable real-reading slices."""
        if page_number < 1:
            raise ValueError(f"page_number must be >= 1, got {page_number}")

        effective_page_size = page_size if page_size is not None else self._default_page_size
        if effective_page_size <= 0:
            raise ValueError(f"page_size must be positive, got {effective_page_size}")
        effective_page_size = min(effective_page_size, self._max_page_size)

        total_records = len(descriptors)
        total_pages = max(1, math.ceil(total_records / effective_page_size)) if total_records > 0 else 1

        start_idx = (page_number - 1) * effective_page_size
        end_idx = min(start_idx + effective_page_size, total_records)

        if start_idx >= total_records and total_records > 0:
            page_items: tuple[ActionDetailDescriptor, ...] = ()
        else:
            page_items = tuple(descriptors[start_idx:end_idx])

        # Compute deterministic real-read slices bound to underlying texts
        slices: list[RealReadSlice] = []
        if text_content_by_ref is not None:
            for item in page_items:
                raw_text = text_content_by_ref.get(item.ref)
                if raw_text is not None:
                    total_len = len(raw_text)
                    read_len = min(total_len, max_text_window)
                    actual_excerpt = raw_text[:read_len]
                    content_sha = hashlib.sha256(actual_excerpt.encode("utf-8")).hexdigest()
                    slices.append(
                        RealReadSlice(
                            unit_id=item.ref,
                            start_offset=0,
                            end_offset=read_len,
                            actual_text=actual_excerpt,
                            content_sha256=content_sha,
                            total_unit_length=total_len,
                        )
                    )

        has_next = page_number < total_pages
        has_previous = page_number > 1

        return PaginatedEvidencePage(
            page_number=page_number,
            page_size=effective_page_size,
            total_records=total_records,
            total_pages=total_pages,
            items=page_items,
            slices=tuple(slices),
            has_next=has_next,
            has_previous=has_previous,
        )
