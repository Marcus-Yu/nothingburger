"""nav: building pre-pass geometry, standoff proposals, base route.

Every argument and return value is a plain dict or list in the contract shapes.
"""
from __future__ import annotations

from . import building, coverage, route, standoff


def corridors(world: dict, tasks: list) -> dict:
    """{"corridors": [...], "demands": {...}} plus "doorways": the cleaned widths."""
    return building.corridors(world, tasks)


def free_floor(world: dict, anchor_id: str, *, radius_m: float) -> dict:
    """{"edge_distance_m", "side", "nearest"} for a disc of radius_m connected to the dock."""
    return standoff.free_floor(world, anchor_id, radius_m=radius_m)


def propose(world: dict, build: dict, task: dict, *, requirements: dict | None = None, limit: int = 12) -> list:
    """Ranked base poses [x, y, yaw] for the task: collision-free and connected to the dock."""
    return standoff.propose(world, build, task, requirements=requirements, limit=limit)


def plan(world: dict, build: dict, *, requirements: dict, standoffs: list) -> dict:
    """A route.json dict: legs, door clearances and recorded failures."""
    return route.plan(world, build, requirements=requirements, standoffs=standoffs)


def cover(area: dict, id_: str = "t1") -> dict | None:
    """The navigate task whose waypoints are back-and-forth passes over one of a world's `areas`, or None."""
    return coverage.task(area, id_)
