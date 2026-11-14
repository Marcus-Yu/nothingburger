"""Base route (step 5b): A* on the grid inflated by the inscribed radius, then a
footprint check with heading along the path. Failures are recorded, not raised.
"""
from __future__ import annotations

import heapq
import math

import numpy as np

from . import grid as G
from .building import passable_doorways

SNAP_M = 0.15            # a stop this close to a free cell is moved onto it
SOFT_MARGIN_M = 0.15     # A* prefers clearance of circumscribed radius + this
SOFT_PENALTY = 4.0
YAW_STEP_DEG = 15
SIDEWAYS_COST = 1.0      # per metre per radian a holonomic base drives off its heading
ROTATE_COST = 0.3        # per radian turned in place
TIGHT_M = 0.15           # footprint clearance under this is penalised
TIGHT_COST = 3.0         # per metre driven with the footprint touching
DOOR_NAME_M = 0.5        # a failure this close to a doorway names it


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def _astar(grid: G.Grid, mask: np.ndarray, start, goal, soft: float):
    """8-connected A* over `mask`, cheaper where clearance is at least `soft`."""
    if not (mask[start] and mask[goal]):
        return None
    ny, nx = mask.shape
    pen = 1.0 + SOFT_PENALTY * np.clip((soft - grid.clearance) / max(soft, 1e-6), 0.0, 1.0)
    cost = np.full(mask.shape, np.inf)
    parent = {}
    cost[start] = 0.0
    heap = [(0.0, start)]
    moves = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
             (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2))]
    done = np.zeros(mask.shape, bool)
    while heap:
        _, cur = heapq.heappop(heap)
        if done[cur]:
            continue
        done[cur] = True
        if cur == goal:
            path = [cur]
            while cur in parent:
                cur = parent[cur]
                path.append(cur)
            return path[::-1]
        i, j = cur
        for di, dj, step in moves:
            a, b = i + di, j + dj
            if not (0 <= a < ny and 0 <= b < nx) or not mask[a, b] or done[a, b]:
                continue
            if di and dj and not (mask[i + di, j] and mask[i, j + dj]):
                continue
            c = cost[cur] + step * 0.5 * (pen[cur] + pen[a, b])
            if c < cost[a, b]:
                cost[a, b] = c
                parent[(a, b)] = cur
                heapq.heappush(heap, (c + math.hypot(a - goal[0], b - goal[1]), (a, b)))
    return None


def _line_ok(grid, mask, a, b, need: float) -> bool:
    n = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / (grid.cell / 2))))
    t = np.linspace(0, 1, n + 1)
    x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
    i, j = grid.index(x, y)
    if not grid.inside(i, j).all() or not mask[i, j].all():
        return False
    return bool(grid.clearance[i, j].min() >= need - 1e-9)


def _shortcut(grid, mask, pts, soft: float):
    """Straighten the cell path without giving up clearance the path had."""
    clr = grid.clearance_at([p[0] for p in pts], [p[1] for p in pts])
    out, i = [pts[0]], 0
    while i < len(pts) - 1:
        j, low = i + 1, min(clr[i], clr[i + 1])
        while j + 1 < len(pts):
            nxt = min(low, clr[j + 1])
            if not _line_ok(grid, mask, pts[i], pts[j + 1], min(soft, nxt)):
                break
            j, low = j + 1, nxt
        out.append(pts[j])
        i = j
    return out


def _resample(poly, ds: float):
    """Samples along the polyline: (points, heading of the segment leaving each, vertex flags)."""
    pts, dirs, vert = [], [], []
    for k in range(len(poly) - 1):
        a, b = poly[k], poly[k + 1]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        th = math.atan2(b[1] - a[1], b[0] - a[0])
        n = max(1, int(math.ceil(L / ds)))
        for m in range(n):
            pts.append((a[0] + (b[0] - a[0]) * m / n, a[1] + (b[1] - a[1]) * m / n))
            dirs.append(th)
            vert.append(m == 0)
    pts.append(tuple(poly[-1]))
    dirs.append(dirs[-1] if dirs else 0.0)
    vert.append(True)
    return pts, dirs, vert


def _headings(grid, samples, pts, dirs, yaw0, yaw1, holonomic, r_out):
    """Choose a heading at every path sample so the true footprint never hits the grid.

    States are (sample, heading). Moving keeps the heading; turning happens in
    place between neighbouring headings that both fit. A non-holonomic base
    moves only with its heading along the path and turns only where its
    circumscribed radius is free. Returns (per-sample (yaw in, yaw out), None)
    or (None, (sample index, reason)).
    """
    n = len(pts)
    cand = {round(_wrap(math.radians(d)), 6) for d in range(-180 + YAW_STEP_DEG, 181, YAW_STEP_DEG)}
    cand |= {round(_wrap(v), 6) for v in dirs} | {round(_wrap(yaw0), 6), round(_wrap(yaw1), 6)}
    yaws = sorted(cand)
    K = len(yaws)
    key = {y: k for k, y in enumerate(yaws)}
    k0, k1 = key[round(_wrap(yaw0), 6)], key[round(_wrap(yaw1), 6)]
    kdir = [key[round(_wrap(v), 6)] for v in dirs]
    px = np.array([p[0] for p in pts])[:, None]
    py = np.array([p[1] for p in pts])[:, None]
    sx, sy = G.placed(samples, np.broadcast_to(px, (n, K)), np.broadcast_to(py, (n, K)),
                      np.broadcast_to(np.array(yaws)[None, :], (n, K)))
    valid = ~grid.occupied_at(sx, sy).any(axis=2)
    tight = TIGHT_COST * np.clip((TIGHT_M - grid.clearance_at(sx, sy).min(axis=2)) / TIGHT_M, 0.0, 1.0)
    clr = grid.clearance_at(px[:, 0], py[:, 0])
    can_turn = np.ones(n, bool) if holonomic else clr >= r_out - 1e-9

    if not valid[0, k0]:
        return None, (0, "the footprint collides at the start pose")
    best = {(0, k0): 0.0}
    parent = {}
    heap = [(0.0, 0, k0)]
    far = 0
    seen = set()
    while heap:
        c, i, k = heapq.heappop(heap)
        if (i, k) in seen:
            continue
        seen.add((i, k))
        far = max(far, i)
        if i == n - 1 and k == k1:
            break
        nxt = []
        if can_turn[i]:
            for k2 in ((k + 1) % K, (k - 1) % K):
                if valid[i, k2]:
                    nxt.append((i, k2, ROTATE_COST * abs(_wrap(yaws[k2] - yaws[k]))))
        if i + 1 < n and valid[i + 1, k] and (holonomic or k == kdir[i]):
            ds = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            nxt.append((i + 1, k, ds * (1.0 + tight[i + 1, k] + SIDEWAYS_COST * abs(_wrap(yaws[k] - dirs[i])))))
        for i2, k2, step in nxt:
            if c + step < best.get((i2, k2), math.inf):
                best[(i2, k2)] = c + step
                parent[(i2, k2)] = (i, k)
                heapq.heappush(heap, (c + step, i2, k2))
    if (n - 1, k1) not in seen:
        if far == n - 1:
            why = ("the footprint does not fit at the goal heading" if not valid[far, k1] else
                   f"no room to turn to the goal heading (needs the circumscribed radius {r_out:.2f} m free, has {clr[far]:.2f} m)"
                   if not holonomic else "the footprint cannot turn to the goal heading here")
            return None, (far, why)
        spot = far + 1
        if holonomic:
            why = "the footprint does not fit at any heading the base can arrive with"
        elif valid[spot, kdir[far]]:
            why = (f"no room to turn onto the path (needs the circumscribed radius {r_out:.2f} m free, "
                   f"has {clr[far]:.2f} m)")
            spot = far
        else:
            why = "the footprint collides with its heading along the path"
        return None, (spot, why)
    chain = [(n - 1, k1)]
    while chain[-1] in parent:
        chain.append(parent[chain[-1]])
    chain.reverse()
    span = [[None, None] for _ in range(n)]
    for i, k in chain:
        if span[i][0] is None:
            span[i][0] = yaws[k]
        span[i][1] = yaws[k]
    return span, None


def _seg_hit(a, b, c, d):
    """Intersection point of segments a-b and c-d, or None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def _door_near(doors, x, y, within=DOOR_NAME_M):
    best, best_d = None, within
    for d in doors:
        p, u, _ = G.door_frame(d)
        s = float(np.clip((x - p[0]) * u[0] + (y - p[1]) * u[1], -d["width_m"] / 2, d["width_m"] / 2))
        dist = math.hypot(x - (p[0] + s * u[0]), y - (p[1] + s * u[1]))
        if dist <= best_d:
            best, best_d = d, dist
    return best


def _width_across(poly, yaw, along) -> float:
    c, s = math.cos(yaw), math.sin(yaw)
    proj = (c * poly[:, 0] - s * poly[:, 1]) * along[0] + (s * poly[:, 0] + c * poly[:, 1]) * along[1]
    return float(proj.max() - proj.min())


def _failure(leg, spot, reason, doors, kind):
    f = {"leg": leg, "kind": kind, "spot": None if spot is None else [round(float(spot[0]), 3), round(float(spot[1]), 3)],
         "doorway": None, "reason": reason}
    if spot is not None:
        d = _door_near(doors, spot[0], spot[1])
        if d is not None:
            f["doorway"] = d["id"]
            f["reason"] = f"at {d['id']} ({d['width_m']:.2f} m wide): {reason}"
    return f


def _why_no_route(grid, r_in, start, goal, soft):
    """The pinch point: shrink the disc until the ends join, then take the
    tightest cell on that route. Returns (spot, reason)."""
    r = r_in
    while r > 0:
        r = max(0.0, r - grid.cell / 2)
        mask = grid.free_mask(r) & ~grid.occ
        s = grid.nearest_in(mask, start[0], start[1], SNAP_M)
        g = grid.nearest_in(mask, goal[0], goal[1], SNAP_M)
        path = _astar(grid, mask, s, g, soft) if s and g else None
        if path:
            cell = min(path, key=lambda c: grid.clearance[c])
            x, y = grid.centre(*cell)
            return (float(x), float(y)), (f"too narrow for the base, which needs {2 * r_in:.2f} m "
                                          "(twice its inscribed radius)")
    return goal, "walled off: no open floor joins the two ends (a closed or dropped doorway?)"


def _leg(grid, world_doors, geom, holonomic, name, a_pose, b_pose):
    """Plan one leg. Returns (leg fields or None, failures, door crossings)."""
    poly, samples, r_in, r_out = geom
    soft = r_out + SOFT_MARGIN_M
    mask = grid.free_mask(r_in)
    ends = []
    for label, pose in (("start", a_pose), ("goal", b_pose)):
        cell = grid.nearest_in(mask, pose[0], pose[1], SNAP_M)
        if cell is None:
            c = float(grid.clearance_at(pose[0], pose[1]))
            return None, [_failure(name, pose[:2], f"the {label} is not free for the base's inscribed radius "
                                   f"{r_in:.2f} m (clearance {c:.2f} m)", world_doors, f"{label}_blocked")], []
        ends.append(cell)
    cells = _astar(grid, mask, ends[0], ends[1], soft)
    if cells is None:
        spot, why = _why_no_route(grid, r_in, a_pose, b_pose, soft)
        return None, [_failure(name, spot, why, world_doors, "no_route")], []
    pts = [(float(a_pose[0]), float(a_pose[1]))]
    for cell in cells:
        x, y = grid.centre(*cell)
        pts.append((float(x), float(y)))
    pts.append((float(b_pose[0]), float(b_pose[1])))
    pts = [p for k, p in enumerate(pts) if k == 0 or math.hypot(p[0] - pts[k - 1][0], p[1] - pts[k - 1][1]) > 1e-6]
    line = _shortcut(grid, mask, pts, soft) if len(pts) > 2 else pts
    if len(line) == 1:
        line = [line[0], line[0]]
    spts, dirs, vert = _resample(line, grid.cell) if line[0] != line[1] or len(line) > 2 else ([line[0]], [a_pose[2]], [True])
    span, bad = _headings(grid, samples, spts, dirs, a_pose[2], b_pose[2], holonomic, r_out)
    failures = []
    if bad is not None:
        failures.append(_failure(name, spts[bad[0]], bad[1], world_doors, "footprint"))
        span = [[dirs[i], dirs[i]] for i in range(len(spts))]
        span[0][0], span[-1][1] = a_pose[2], b_pose[2]
    way = []
    for i, p in enumerate(spts):
        yin, yout = span[i]
        turned = abs(_wrap(yout - yin)) > 1e-6
        if vert[i] or turned:
            way.append([round(p[0], 3), round(p[1], 3), round(yin, 4)])
        if turned:
            way.append([round(p[0], 3), round(p[1], 3), round(yout, 4)])
    length = sum(math.hypot(line[k + 1][0] - line[k][0], line[k + 1][1] - line[k][1]) for k in range(len(line) - 1))
    crossings = []
    for d in world_doors:
        p, u, _ = G.door_frame(d)
        e0, e1 = p - u * d["width_m"] / 2, p + u * d["width_m"] / 2
        for i in range(len(spts) - 1):
            if _seg_hit(spts[i], spts[i + 1], e0, e1) is not None:
                width = _width_across(poly, span[i][1], u)
                crossings.append((d, width))
                # the grid is good to a cell; the stated width decides a close call
                if width > d["width_m"] and bad is None:
                    failures.append(_failure(name, p, f"the base is {width:.2f} m across at its heading here, "
                                             "wider than the doorway", world_doors, "footprint"))
                break
    leg = {"length_m": round(length, 3), "waypoints": way, "footprint_ok": not failures}
    return leg, failures, crossings


def plan(world: dict, build: dict, *, requirements: dict, standoffs: list) -> dict:
    poly, r_in, r_out = G.base_geometry(build)
    holonomic = bool(build["base"].get("holonomic"))
    grid = G.from_world(world, (0.05, float(build["stowed"]["height_m"])))
    samples = G.footprint_samples(poly, grid.cell / 2)
    doors = passable_doorways(world)
    anchors = {a["id"]: a for a in world.get("anchors", [])}
    failures = []

    dock = [float(v) for v in world["dock"]["pose"][:3]]
    stops = [{"name": "dock", "pose": dock}]
    for t in (requirements or {}).get("tasks", []):
        mine = [(k, s) for k, s in enumerate(standoffs or []) if s.get("task") == t["id"]]
        if not mine:
            if t.get("skill") != "navigate":
                a = anchors.get(t.get("anchor"))
                failures.append(_failure(None, a["point"][:2] if a else None,
                                         f"no standoff was picked for task {t['id']}", [], "no_standoff"))
            continue
        for k, s in mine:
            stops.append({"name": t["id"], "pose": [float(v) for v in s["pose"][:3]], "standoff": k})
        if t.get("carries"):
            out, _ = G.way_out_point(world)
            if out is None:
                failures.append(_failure(f"{t['id']}->way_out", None,
                                         "the way-out doorway is missing, closed or dropped", [], "no_way_out"))
            else:
                stops.append({"name": "way_out", "pose": out, "carrying": True})
    stops.append({"name": "dock", "pose": dock})

    legs, clear = [], {}
    geom = (poly, samples, r_in, r_out)
    for a, b in zip(stops[:-1], stops[1:]):
        name = f"{a['name']}->{b['name']}"
        leg, fails, crossings = _leg(grid, doors, geom, holonomic, name, a["pose"], b["pose"])
        failures.extend(fails)
        if leg is None:
            continue
        entry = {"from": a["name"], "to": b["name"], "carrying": bool(b.get("carrying")), **leg}
        if "standoff" in b:
            entry["standoff"] = b["standoff"]
        legs.append(entry)
        for d, width in crossings:
            row = clear.get(d["id"])
            if row is None or width > row["robot_width_m"]:
                row = clear[d["id"]] = {"doorway": d["id"], "clear_width_m": float(d["width_m"]),
                                        "robot_width_m": round(width, 3),
                                        "margin_m": round((float(d["width_m"]) - width) / 2, 3),
                                        "legs": row["legs"] if row else []}
            row["legs"].append(name)
    return {"schema": "route/1", "world": world.get("id"), "standoffs": [dict(s) for s in (standoffs or [])],
            "legs": legs, "door_clearances": list(clear.values()), "failures": failures}
