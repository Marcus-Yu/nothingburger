"""Free floor near an anchor (pre-pass) and standoff proposals (step 5a, part 1)."""
from __future__ import annotations

import math

import numpy as np

from . import grid as G

RING_START_M = 0.2
RING_STEP_M = 0.05
RING_ANGLE_DEG = 15
CLEARANCE_CAP_M = 0.10     # clearance beyond this does not improve a pose's rank
CLEARANCE_BUCKET_M = 0.05


def _anchor(world: dict, anchor_id: str) -> dict:
    for a in world.get("anchors", []):
        if a["id"] == anchor_id:
            return a
    raise KeyError(f"anchor {anchor_id!r} is not in the world")


def free_floor(world: dict, anchor_id: str, *, radius_m: float) -> dict:
    """Closest spot to the anchor's floor projection where a disc of radius_m,
    connected to the dock, fits. edge_distance_m is measured to the disc's edge.

    When no such spot exists (dock blocked for that radius) edge_distance_m and
    nearest are None.
    """
    a = _anchor(world, anchor_id)
    px, py = float(a["point"][0]), float(a["point"][1])
    grid = G.from_world(world, G.PREPASS_BAND_M)
    dock = world["dock"]["pose"]
    reach = grid.reachable(radius_m, dock[0], dock[1])
    if reach is None or not reach.any():
        return {"edge_distance_m": None, "side": [0.0, 0.0], "nearest": None}
    ii, jj = np.nonzero(reach)
    cx, cy = grid.centre(ii, jj)
    d = np.hypot(cx - px, cy - py)
    k = int(np.argmin(d))
    dist = float(d[k])
    edge = max(0.0, dist - radius_m)
    side = [0.0, 0.0]
    if edge > 0.0:
        side = [round(float(cx[k] - px) / dist, 4), round(float(cy[k] - py) / dist, 4)]
    return {"edge_distance_m": round(edge, 3), "side": side,
            "nearest": [round(float(cx[k]), 3), round(float(cy[k]), 3)]}


def propose(world: dict, build: dict, task: dict, *, requirements: dict | None = None, limit: int = 12) -> list:
    """Ranked base poses [x, y, yaw] for the task: footprint clear of the grid,
    centre connected to the dock for the inscribed radius, and no wall between
    the pose and the anchor's floor projection (obstacles may lie between: a
    counter anchor is inside its counter).

    Rank: footprint clearance (capped at 0.10 m, in 0.05 m steps), then closeness
    to the anchor, then heading (facing the anchor first). Each position is
    listed once with its best heading before any position's other headings.
    """
    a = _anchor(world, task["anchor"])
    px, py = float(a["point"][0]), float(a["point"][1])
    poly, r_in, r_out = G.base_geometry(build)
    grid = G.from_world(world, (0.05, float(build["stowed"]["height_m"])))
    dock = world["dock"]["pose"]
    reach = grid.reachable(r_in, dock[0], dock[1])
    if reach is None:
        return []
    walls = G.from_world(dict(world, obstacles=[]), (0.0, 0.0))  # for "no wall between pose and anchor"
    r_max = max((float(e["max_distance_m"]) for e in build.get("reach_envelope", [])), default=RING_START_M)
    radii = np.arange(RING_START_M, r_max + 1e-9, RING_STEP_M)
    angles = np.deg2rad(np.arange(0, 360, RING_ANGLE_DEG))
    rr, aa = (v.ravel() for v in np.meshgrid(radii, angles, indexing="ij"))
    xs, ys = px + rr * np.cos(aa), py + rr * np.sin(aa)
    i, j = grid.index(xs, ys)
    ok = grid.inside(i, j)
    ok[ok] = reach[i[ok], j[ok]]
    if not build["base"].get("holonomic"):
        # plan() lets such a base turn only where its circumscribed radius is free,
        # and it has to turn to the standoff heading
        ok &= grid.clearance_at(xs, ys) >= r_out - 1e-9
    # sight line from just off the anchor (a wall-mounted fixture sits in a wall cell) to the pose
    t = np.linspace(0.0, 1.0, int(math.ceil(r_max / (grid.cell / 2))) + 1)
    t0 = np.minimum(1.0, 2 * grid.cell / rr)[:, None]
    t = t0 + (1.0 - t0) * t
    ok &= ~walls.occupied_at(px + (xs[:, None] - px) * t, py + (ys[:, None] - py) * t).any(axis=1)
    xs, ys, rr, aa = xs[ok], ys[ok], rr[ok], aa[ok]
    if xs.size == 0:
        return []
    samples = G.footprint_samples(poly, grid.cell / 2)
    found = []
    for h in range(4):
        yaw = aa + math.pi + h * math.pi / 2
        sx, sy = G.placed(samples, xs, ys, yaw)
        hit = grid.occupied_at(sx, sy).any(axis=1)
        clear = grid.clearance_at(sx, sy).min(axis=1)
        for k in np.nonzero(~hit)[0]:
            bucket = int(min(clear[k], CLEARANCE_CAP_M) / CLEARANCE_BUCKET_M + 1e-6)
            w = math.atan2(math.sin(yaw[k]), math.cos(yaw[k]))
            found.append(((-bucket, round(float(rr[k]), 3), h, round(float(aa[k]), 4)),
                          (round(float(xs[k]), 3), round(float(ys[k]), 3)), round(w, 4)))
    found.sort()
    first, rest, seen = [], [], set()
    for _, pos, yaw in found:
        (rest if pos in seen else first).append([pos[0], pos[1], yaw])
        seen.add(pos)
    return (first + rest)[:max(0, int(limit))]
