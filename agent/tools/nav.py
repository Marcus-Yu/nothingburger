"""nav.api, traced. Pass-throughs, plus `moved` and `free_floor_at`: nav measures around an anchor's point, so
asking about another point on the anchor (one wipe stroke end) is done on a copy of the world."""
from __future__ import annotations

import copy

import nav.api as _api

from .trace import traced


def _corridors_summary(r):
    d = r["demands"]
    return (f"{len(r['corridors'])} corridors; narrowest {d['narrowest_m']} m at {d['narrowest_doorway']}; "
            f"header {d['lowest_header_m']} m; step {d['tallest_step_m']} m; turn {d['tightest_turn_m']} m")


@traced("nav.corridors", _corridors_summary)
def corridors(world: dict, tasks: list) -> dict:
    return _api.corridors(world, tasks)


@traced("nav.free_floor", lambda r: f"edge {r['edge_distance_m']} m, side {r['side']}")
def free_floor(world: dict, anchor_id: str, *, radius_m: float) -> dict:
    return _api.free_floor(world, anchor_id, radius_m=radius_m)


def moved(world: dict, anchor_id: str, point) -> dict:
    """A copy of the world with one anchor's point moved to `point` in the floor plane (its height is kept).
    The copy is for nav only; nothing is written back."""
    out = copy.deepcopy(world)
    for a in out.get("anchors", []):
        if a["id"] == anchor_id:
            a["point"] = [float(point[0]), float(point[1]), float(a["point"][2])]
    return out


def free_floor_at(world: dict, anchor_id: str, point, *, radius_m: float) -> dict:
    """nav.free_floor measured to `point` instead of the anchor's own point."""
    return free_floor(moved(world, anchor_id, point), anchor_id, radius_m=radius_m)


@traced("nav.propose", lambda r: f"{len(r)} poses" + (f", first {r[0]}" if r else ""))
def propose(world: dict, build: dict, task: dict, *, requirements: dict | None = None, limit: int = 12) -> list:
    return _api.propose(world, build, task, requirements=requirements, limit=limit)


@traced("nav.plan", lambda r: f"{len(r['legs'])} legs, {len(r['door_clearances'])} doors crossed, {len(r['failures'])} failures")
def plan(world: dict, build: dict, *, requirements: dict, standoffs: list) -> dict:
    return _api.plan(world, build, requirements=requirements, standoffs=standoffs)
