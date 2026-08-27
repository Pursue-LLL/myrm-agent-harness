"""MAP-Elites Gene Bank Archive for Skill and Harness Evolution.

Maintains quality-diversity Pareto elites across a two-dimensional grid:
- Dimension 1 (EvolutionLayer): PROMPT, TOOL_CODE, RUNTIME_CONFIG, KNOWLEDGE_RULE
- Dimension 2 (FailurePathology): PARAM_ERROR, TIMEOUT_RETRY, ENV_MISSING,
                                SEMANTIC_MISUSE, LOGIC_HALLUCINATION, UNHANDLED_EXCEPTION

Prevents greedy single-objective evolution collapse (e.g. over-fitting to conservative prompt tweaks).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionLayer,
    FailurePathology,
    GeneCellKey,
    GeneEliteRecord,
)

logger = logging.getLogger(__name__)


class GeneBankArchive:
    """In-memory and persistent archive for MAP-Elites gene cells."""

    def __init__(self, max_elites_per_cell: int = 2) -> None:
        self.max_elites_per_cell = max_elites_per_cell
        self._archive: dict[str, list[GeneEliteRecord]] = defaultdict(list)

    def record_elite(self, record: GeneEliteRecord) -> bool:
        """Record or update an elite candidate in its corresponding gene cell.

        Returns True if the record was admitted or updated in the cell.
        """
        cell_key_str = record.cell_key.to_key_str()
        current_elites = self._archive[cell_key_str]

        # Check if record is better than worst elite in cell
        if len(current_elites) < self.max_elites_per_cell:
            current_elites.append(record)
            current_elites.sort(key=lambda x: x.fitness_score, reverse=True)
            return True

        if record.fitness_score > current_elites[-1].fitness_score:
            current_elites[-1] = record
            current_elites.sort(key=lambda x: x.fitness_score, reverse=True)
            return True

        return False

    def get_cell_elites(self, cell_key: GeneCellKey) -> list[GeneEliteRecord]:
        """Get all elites within a specific cell."""
        return list(self._archive.get(cell_key.to_key_str(), []))

    def get_diverse_elites(
        self,
        target_pathology: FailurePathology | None = None,
        limit_per_layer: int = 1,
    ) -> list[GeneEliteRecord]:
        """Retrieve diverse elite exemplars across different layers for few-shot prompt assembly."""
        diverse_elites: list[GeneEliteRecord] = []
        for layer in EvolutionLayer:
            matching_records: list[GeneEliteRecord] = []
            if target_pathology:
                cell_key = GeneCellKey(layer=layer, pathology=target_pathology)
                matching_records = self.get_cell_elites(cell_key)

            if not matching_records:
                # Fallback to any elite in this layer
                for p in FailurePathology:
                    cell_key = GeneCellKey(layer=layer, pathology=p)
                    elites = self.get_cell_elites(cell_key)
                    if elites:
                        matching_records.extend(elites)
                        break

            if matching_records:
                matching_records.sort(key=lambda x: x.fitness_score, reverse=True)
                diverse_elites.extend(matching_records[:limit_per_layer])

        return diverse_elites

    def get_coverage_matrix(self) -> dict[str, dict[str, int]]:
        """Return full 2D coverage matrix (Layer x Pathology -> count of elites)."""
        matrix: dict[str, dict[str, int]] = {}
        for layer in EvolutionLayer:
            matrix[layer.value] = {}
            for pathology in FailurePathology:
                cell_key = GeneCellKey(layer=layer, pathology=pathology)
                count = len(self._archive.get(cell_key.to_key_str(), []))
                matrix[layer.value][pathology.value] = count
        return matrix

    def to_dict(self) -> dict[str, Any]:
        """Serialize full archive to dictionary."""
        serialized_archive: dict[str, list[dict[str, Any]]] = {}
        for cell_key_str, records in self._archive.items():
            serialized_archive[cell_key_str] = [rec.to_dict() for rec in records]
        return {
            "max_elites_per_cell": self.max_elites_per_cell,
            "archive": serialized_archive,
            "coverage": self.get_coverage_matrix(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GeneBankArchive:
        """Deserialize archive from dictionary."""
        max_elites = int(data.get("max_elites_per_cell", 2))
        archive_inst = cls(max_elites_per_cell=max_elites)
        raw_archive = data.get("archive", {})
        for cell_key_str, records_data in raw_archive.items():
            archive_inst._archive[cell_key_str] = [
                GeneEliteRecord.from_dict(rec) for rec in records_data
            ]
        return archive_inst
