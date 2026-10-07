"""Text-length adaptive batching operator for re-embedding pipelines.

Dynamically partitions incoming memory records into adaptive slices
respecting character limits (to prevent GPU/vLLM OOM) and target batch limits.

[INPUT]
- toolkits.memory.reembedding.models::ReembeddingBatch, ReembeddingJobConfig, ReembeddingRecord (POS: Data
  models for ZeroDowntimeCrossDimensionReembeddingEngine.)

[OUTPUT]
- AdaptiveBatcher: Partitions memory records into adaptive batches based on character volume and record
  count.

[POS]
Text-length adaptive batching operator for re-embedding pipelines.
"""

from collections.abc import Sequence

from .models import ReembeddingBatch, ReembeddingJobConfig, ReembeddingRecord


class AdaptiveBatcher:
    """Partitions memory records into adaptive batches based on character volume and record count."""

    @staticmethod
    def slice_into_batches(
        records: Sequence[ReembeddingRecord],
        config: ReembeddingJobConfig,
    ) -> list[ReembeddingBatch]:
        """Slice input records into balanced batches within character thresholds."""
        if not records:
            return []

        batches: list[ReembeddingBatch] = []
        current_records: list[ReembeddingRecord] = []
        current_chars = 0
        batch_id = 0

        for record in records:
            record_len = len(record.content)

            # Case 1: Record alone exceeds max char threshold -> dedicated single-item batch
            if record_len >= config.max_chars_per_batch:
                if current_records:
                    batch_id += 1
                    batches.append(
                        ReembeddingBatch(
                            batch_id=batch_id,
                            records=current_records,
                            total_characters=current_chars,
                        )
                    )
                    current_records = []
                    current_chars = 0

                batch_id += 1
                batches.append(
                    ReembeddingBatch(
                        batch_id=batch_id,
                        records=[record],
                        total_characters=record_len,
                    )
                )
                continue

            # Case 2: Adding this record exceeds max chars or max batch size -> flush current batch
            reached_max_size = len(current_records) >= config.max_batch_size
            exceeded_char_budget = (
                current_records
                and (current_chars + record_len) > config.max_chars_per_batch
                and len(current_records) >= config.min_batch_size
            )

            if reached_max_size or exceeded_char_budget:
                batch_id += 1
                batches.append(
                    ReembeddingBatch(
                        batch_id=batch_id,
                        records=current_records,
                        total_characters=current_chars,
                    )
                )
                current_records = [record]
                current_chars = record_len
            else:
                current_records.append(record)
                current_chars += record_len

        if current_records:
            batch_id += 1
            batches.append(
                ReembeddingBatch(
                    batch_id=batch_id,
                    records=current_records,
                    total_characters=current_chars,
                )
            )

        return batches
