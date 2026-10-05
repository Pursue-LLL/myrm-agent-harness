from __future__ import annotations

import math
from typing import Final

from myrm_agent_harness.toolkits.artifacts.models import (
    BoundingBox2D,
    LODLevel,
    Point2D,
)

LOD1_TOLERANCE_RATIO: Final[float] = 0.005
LOD2_TOLERANCE_RATIO: Final[float] = 0.020


class DouglasPeuckerSimplifier:
    """High-performance 2D geometric simplification operator.

    Adapted from PCB_lightgraph dp_simplify.cpp industrial implementation with
    perpendicular distance caching and adaptive epsilon derivation.
    """

    @staticmethod
    def perpendicular_distance(
        pt: Point2D, line_start: Point2D, line_end: Point2D
    ) -> float:
        dx = line_end.x - line_start.x
        dy = line_end.y - line_start.y
        denom = math.sqrt(dx * dx + dy * dy)
        if denom == 0.0:
            return pt.distance_to(line_start)
        numer = abs(
            dy * pt.x - dx * pt.y + line_end.x * line_start.y - line_end.y * line_start.x
        )
        return numer / denom

    @classmethod
    def simplify_polyline(
        cls, points: list[Point2D], epsilon: float
    ) -> list[Point2D]:
        if len(points) <= 2 or epsilon <= 0.0:
            return list(points)

        idx_max = 0
        dist_max = 0.0
        start_pt = points[0]
        end_pt = points[-1]

        for i in range(1, len(points) - 1):
            dist = cls.perpendicular_distance(points[i], start_pt, end_pt)
            if dist > dist_max:
                dist_max = dist
                idx_max = i

        if dist_max > epsilon:
            left_segment = cls.simplify_polyline(points[: idx_max + 1], epsilon)
            right_segment = cls.simplify_polyline(points[idx_max:], epsilon)
            return left_segment[:-1] + right_segment

        return [start_pt, end_pt]

    @classmethod
    def simplify_polygon(
        cls, points: list[Point2D], epsilon: float, min_points: int = 3
    ) -> list[Point2D]:
        if len(points) <= min_points or epsilon <= 0.0:
            return list(points)

        is_closed = (
            len(points) >= 2
            and points[0].x == points[-1].x
            and points[0].y == points[-1].y
        )
        working_points = points[:-1] if is_closed else points

        if len(working_points) <= min_points:
            return list(points)

        simplified = cls.simplify_polyline(working_points, epsilon)
        if len(simplified) < min_points:
            simplified = working_points[:min_points]

        if is_closed:
            simplified.append(simplified[0])

        return simplified

    @staticmethod
    def compute_adaptive_epsilon(
        bbox: BoundingBox2D, lod_level: LODLevel
    ) -> float:
        diag = bbox.diagonal
        if diag <= 0.0:
            return 0.0

        if lod_level == LODLevel.LOD0_ORIGINAL:
            return 0.0
        if lod_level == LODLevel.LOD1_SIMPLIFIED:
            return diag * LOD1_TOLERANCE_RATIO
        return diag * LOD2_TOLERANCE_RATIO


class EdgeSharpener:
    """Feature angle detector and corner preservation anchor.

    Adapted from PCB_lightgraph edgesharpener.cpp to prevent corner distortion
    during geometric polygon reduction.
    """

    @staticmethod
    def calculate_interior_angle_degrees(
        prev_pt: Point2D, curr_pt: Point2D, next_pt: Point2D
    ) -> float:
        v1_x = prev_pt.x - curr_pt.x
        v1_y = prev_pt.y - curr_pt.y
        v2_x = next_pt.x - curr_pt.x
        v2_y = next_pt.y - curr_pt.y

        mag1 = math.sqrt(v1_x * v1_x + v1_y * v1_y)
        mag2 = math.sqrt(v2_x * v2_x + v2_y * v2_y)
        if mag1 == 0.0 or mag2 == 0.0:
            return 180.0

        cos_theta = (v1_x * v2_x + v1_y * v2_y) / (mag1 * mag2)
        clamped_cos = max(-1.0, min(1.0, cos_theta))
        return math.degrees(math.acos(clamped_cos))

    @classmethod
    def find_critical_corners(
        cls, points: list[Point2D], max_angle_degrees: float = 120.0
    ) -> set[int]:
        if len(points) < 3:
            return set()

        critical_indices: set[int] = {0, len(points) - 1}
        for i in range(1, len(points) - 1):
            angle = cls.calculate_interior_angle_degrees(
                points[i - 1], points[i], points[i + 1]
            )
            if angle <= max_angle_degrees:
                critical_indices.add(i)

        return critical_indices

    @classmethod
    def simplify_with_corner_preservation(
        cls,
        points: list[Point2D],
        epsilon: float,
        max_angle_degrees: float = 120.0,
    ) -> list[Point2D]:
        if len(points) <= 3 or epsilon <= 0.0:
            return list(points)

        critical_indices = sorted(
            cls.find_critical_corners(points, max_angle_degrees)
        )
        if len(critical_indices) <= 2:
            return DouglasPeuckerSimplifier.simplify_polyline(points, epsilon)

        result: list[Point2D] = []
        for i in range(len(critical_indices) - 1):
            sub_start = critical_indices[i]
            sub_end = critical_indices[i + 1]
            sub_points = points[sub_start : sub_end + 1]
            sub_simplified = DouglasPeuckerSimplifier.simplify_polyline(
                sub_points, epsilon
            )
            if not result:
                result.extend(sub_simplified)
            else:
                result.extend(sub_simplified[1:])

        return result
