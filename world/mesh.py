"""Furniture and table tops measured on a scan mesh, for world/matterport.py.

The mesh is sampled into points, the points are binned on a floor grid inside the rooms and away from the
walls, and two things are read off the bins:

  obstacles  whatever stands between LOW_M and HIGH_M above the floor, as boxes on a 0.1 m grid. Cells of
             about the same height are boxed together, so a table keeps its own height and the arm may
             reach over it. What hangs over a gap (a lamp over a table, a wall cabinet) is boxed apart,
             with its own underside.
  anchors    flat, level patches at table or counter height with nothing on them, as `surface` anchors
             whose `extent` is the largest rectangle that fits in the patch. Those with free floor along
             one side come first. A flat top is not known to be a table: a made bed can pass.

Boxes and extents are aligned with the world's axes, so a building scanned at an angle to them gets
boxes that are too big. numpy and scipy only.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import ndimage

CELL_M = 0.05
BOX_CELL = 2              # obstacle boxes are cut on CELL_M * BOX_CELL
POINTS_PER_M2 = 2500.0
LOW_M, HIGH_M = 0.10, 2.0  # the band the robot's body and arm move in
LAYER_M, GAP_M = 0.1, 0.4  # a column is read in slices
HANG_M = 1.2              # what starts above this, over an empty stretch of GAP_M, hangs (a lamp, a wall cabinet)
STEP_M = 0.12             # cells boxed together differ in height by no more than this
WALL_PAD_M = 0.07         # mesh this close to a wall's face is the wall
MIN_HITS = 3              # points in a cell before it counts
MIN_BOX_M2 = 0.03
TOP_LOW_M, TOP_HIGH_M = 0.62, 1.15   # table and counter heights; lower flat things are beds and seats
TOP_FLAT_M = 0.02         # neighbouring cells of one top differ by less
TOP_LEVEL_M = 0.025       # and the whole top stays within this (5th to 95th percentile)
TOP_ROOM_M = 0.35         # nothing may hang lower than this over a top
TOP_MIN_SIDE_M, TOP_MIN_M2 = 0.3, 0.3
TOP_APPROACH_M = 0.5      # a top is approachable when the floor this deep along one of its sides is mostly free


def read_obj(path: str | Path) -> tuple:
    """(vertices n x 3, triangles m x 3) of an OBJ; polygons are fanned, texture and normal indices dropped."""
    verts, faces = [], []
    with open(path, "rb") as f:
        for line in f:
            if line.startswith(b"v "):
                verts.append(line[2:].split()[:3])
            elif line.startswith(b"f "):
                idx = [int(p.split(b"/", 1)[0]) for p in line[2:].split()]
                for k in range(1, len(idx) - 1):
                    faces.append((idx[0], idx[k], idx[k + 1]))
    v = np.array(verts, dtype=float)
    t = np.array(faces, dtype=np.int64)
    t = np.where(t < 0, t + len(v), t - 1)
    return v, t


def sample(vertices: np.ndarray, triangles: np.ndarray, per_m2: float = POINTS_PER_M2, seed: int = 0) -> tuple:
    """(points n x 3, the up component of each point's face normal), spread evenly over the mesh's area."""
    a, b, c = (vertices[triangles[:, k]] for k in range(3))
    cross = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    rng = np.random.default_rng(seed)
    count = rng.poisson(area * per_m2)
    which = np.repeat(np.arange(len(triangles)), count)
    u, v = rng.random(len(which)), rng.random(len(which))
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    points = a[which] + u[:, None] * (b[which] - a[which]) + v[:, None] * (c[which] - a[which])
    up = np.abs(cross[:, 2]) / np.maximum(2 * area, 1e-12)
    return points, up[which]


def _in_polygon(x: np.ndarray, y: np.ndarray, poly: list) -> np.ndarray:
    hit = np.zeros(x.shape, bool)
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
        if ay == by:
            continue
        cross = ((ay > y) != (by > y)) & (x < ax + (y - ay) * (bx - ax) / (by - ay))
        hit ^= cross
    return hit


def _near_walls(x: np.ndarray, y: np.ndarray, walls: list) -> np.ndarray:
    near = np.zeros(x.shape, bool)
    for w in walls:
        a, b = np.array(w["a"], float), np.array(w["b"], float)
        d = b - a
        t = np.clip(((x - a[0]) * d[0] + (y - a[1]) * d[1]) / max(float(d @ d), 1e-12), 0, 1)
        near |= np.hypot(x - (a[0] + t * d[0]), y - (a[1] + t * d[1])) <= w["thickness_m"] / 2 + WALL_PAD_M
    return near


def _rectangles(height: np.ndarray, step: float) -> list:
    """Cut the finite cells of `height` into rectangles of about one height: [(i0, j0, i1, j1, top)], ends
    exclusive. From the tallest cells down, the largest rectangle of cells within `step` of the tallest left
    is taken out, until none are left."""
    todo = np.isfinite(height)
    out = []
    while todo.any():
        level = todo & (height >= np.max(height[todo]) - step)
        while level.any():
            i0, j0, i1, j1 = _largest_rectangle(level)
            out.append((i0, j0, i1, j1, float(np.max(height[i0:i1, j0:j1]))))
            level[i0:i1, j0:j1] = False
            todo[i0:i1, j0:j1] = False
    return out


def _largest_rectangle(mask: np.ndarray) -> tuple | None:
    """(i0, j0, i1, j1) of the largest all-true rectangle in `mask`, ends exclusive."""
    best, heights = None, np.zeros(mask.shape[1], int)
    for i in range(mask.shape[0]):
        heights = np.where(mask[i], heights + 1, 0)
        stack: list = []
        for j in range(mask.shape[1] + 1):
            h = heights[j] if j < mask.shape[1] else 0
            start = j
            while stack and stack[-1][1] >= h:
                start, top = stack.pop()
                if best is None or top * (j - start) > best[0]:
                    best = (top * (j - start), i - top + 1, start, i + 1, j)
            stack.append((start, h))
    return None if best is None or best[0] == 0 else best[1:]


def furniture(obj_path: str | Path, plan: dict) -> dict:
    """{"obstacles": [...], "anchors": [...]} for the rooms of `plan` (world.matterport.layout's result)."""
    vertices, triangles = read_obj(obj_path)
    points, up = sample(vertices, triangles)
    obstacles, anchors = [], []
    floors = sorted(plan["floors"], key=lambda f: f["z"])
    for n, floor in enumerate(floors):
        rooms = [r for r in plan["rooms"] if r["floor"] == floor["id"]]
        if not rooms:
            continue
        above = floors[n + 1]["z"] if n + 1 < len(floors) else np.inf
        corners = np.array([p for r in rooms for p in r["polygon"]], float)
        x0, y0 = np.floor(corners.min(axis=0) / CELL_M) * CELL_M
        nx, ny = (np.ceil((corners.max(axis=0) - (x0, y0)) / CELL_M).astype(int) // BOX_CELL + 1) * BOX_CELL
        cx, cy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * CELL_M, y0 + (np.arange(ny) + 0.5) * CELL_M)
        room_at = np.full((ny, nx), -1)
        for k, r in enumerate(rooms):
            room_at[_in_polygon(cx, cy, r["polygon"])] = k
        open_floor = (room_at >= 0) & ~_near_walls(cx, cy, [w for w in plan["walls"] if w["floor"] == floor["id"]])

        h = points[:, 2] - floor["z"]
        j = np.floor((points[:, 0] - x0) / CELL_M).astype(int)
        i = np.floor((points[:, 1] - y0) / CELL_M).astype(int)
        high = min(HIGH_M, above - floor["z"])
        slices = int(np.ceil((high - LOW_M) / LAYER_M))
        keep = (i >= 0) & (i < ny) & (j >= 0) & (j < nx) & (h > LOW_M) & (h < high)
        i, j, h, flat = i[keep], j[keep], h[keep], up[keep] > 0.95

        # each cell's column, in LAYER_M slices: the first filled slice above HANG_M that has GAP_M of nothing
        # under it starts the part that hangs (a lamp over a table); everything below it stands on the floor
        k = np.minimum(((h - LOW_M) / LAYER_M).astype(int), slices - 1)
        filled = np.zeros((ny, nx, slices), int)
        np.add.at(filled, (i, j, k), 1)
        filled = filled >= 2
        real = filled[i, j, k]                          # a lone point in a slice is noise
        i, j, h, k, flat = i[real], j[real], h[real], k[real], flat[real]
        stand_end = np.full((ny, nx), slices)          # slice index where the hanging part starts
        gap, done = np.zeros((ny, nx), int), np.zeros((ny, nx), bool)
        for s in range(slices):
            hangs = filled[:, :, s] & ~done & (gap * LAYER_M >= GAP_M) & (LOW_M + s * LAYER_M >= HANG_M)
            stand_end[hangs] = s
            done |= hangs
            gap = np.where(filled[:, :, s], 0, gap + 1)
        standing = k < stand_end[i, j]
        top = np.full((ny, nx), -np.inf)
        np.maximum.at(top, (i[standing], j[standing]), h[standing])
        hits = np.zeros((ny, nx), int)
        np.add.at(hits, (i[standing], j[standing]), 1)
        hang_low, hang_top = np.full((ny, nx), np.inf), np.full((ny, nx), -np.inf)
        np.minimum.at(hang_low, (i[~standing], j[~standing]), h[~standing])
        np.maximum.at(hang_top, (i[~standing], j[~standing]), h[~standing])
        hang_hits = np.zeros((ny, nx), int)
        np.add.at(hang_hits, (i[~standing], j[~standing]), 1)

        # obstacles, on the coarser grid: a coarse cell is as tall as its tallest fine cell
        def coarse(a, fn):
            return fn(a.reshape(ny // BOX_CELL, BOX_CELL, nx // BOX_CELL, BOX_CELL), axis=(1, 3))
        c_room = coarse(room_at, np.max)
        size = CELL_M * BOX_CELL
        for hanging, solid, tops_at, lows_at in ((False, open_floor & (hits >= MIN_HITS), top, None),
                                                 (True, open_floor & (hang_hits >= MIN_HITS), hang_top, hang_low)):
            c_top = coarse(np.where(solid, tops_at, -np.inf), np.max)
            cells = np.isfinite(c_top)
            labels, _ = ndimage.label(cells)
            area = ndimage.sum_labels(cells, labels, np.arange(labels.max() + 1)) * size * size
            cells &= area[labels] >= MIN_BOX_M2
            c_top = np.where(cells, c_top, -np.inf)
            closed = ndimage.binary_closing(cells, np.ones((3, 3), bool))     # fill one-cell nicks and holes
            c_top = np.where(closed, ndimage.maximum_filter(c_top, size=3), -np.inf)
            cells = closed
            # a cell the closing filled has no reading of its own: it takes its neighbours' underside
            c_low = ndimage.minimum_filter(coarse(np.where(solid, lows_at, np.inf), np.min), size=3) if hanging else None
            for i0, j0, i1, j1, tall in _rectangles(np.where(cells, c_top, np.nan), STEP_M):
                low = float(np.min(c_low[i0:i1, j0:j1])) if hanging else 0.0
                obstacles.append({"id": f"scan_{len(obstacles) + 1}", "room": rooms[int(c_room[i0:i1, j0:j1].max())]["id"],
                                  "source": "mesh", "box": {
                    "min": [round(float(x0 + j0 * size), 2), round(float(y0 + i0 * size), 2), round(floor["z"] + low, 2)],
                    "max": [round(float(x0 + j1 * size), 2), round(float(y0 + i1 * size), 2), round(floor["z"] + tall, 2)]}})

        # table tops: cells at table height whose highest points are level, with room above
        level_sum, level_n = np.zeros((ny, nx)), np.zeros((ny, nx), int)
        flat &= standing & (h >= top[i, j] - TOP_FLAT_M)     # only the level points at the very top of the column
        np.add.at(level_sum, (i[flat], j[flat]), h[flat])
        np.add.at(level_n, (i[flat], j[flat]), 1)
        level = np.where(level_n >= 2, level_sum / np.maximum(level_n, 1), np.nan)
        bare = open_floor & np.isfinite(level) & (level >= TOP_LOW_M) & (level <= TOP_HIGH_M) & (hang_low - level >= TOP_ROOM_M)
        # a top is one connected patch of cells that step less than TOP_FLAT_M to their neighbours and, taken
        # together, stay level: a bed or a cushion slopes more than a table does
        padded = np.pad(np.where(bare, level, np.nan), 1, constant_values=np.nan)
        steps = np.stack([np.abs(padded[1:-1, 1:-1] - padded[1 + di:ny + 1 + di, 1 + dj:nx + 1 + dj])
                          for di, dj in ((0, 1), (0, -1), (1, 0), (-1, 0))])
        smooth = bare & ~(np.nan_to_num(steps, nan=0.0) > TOP_FLAT_M).any(axis=0)
        labels, count = ndimage.label(smooth)
        tops = []
        for k in range(1, count + 1):
            patch = labels == k
            if patch.sum() * CELL_M * CELL_M < TOP_MIN_M2:
                continue
            low, high = np.percentile(level[patch], [5, 95])
            if high - low > TOP_LEVEL_M:
                continue
            patch = ndimage.binary_closing(patch, np.ones((3, 3), bool)) & open_floor   # sampling leaves pinholes
            i0, j0, i1, j1 = _largest_rectangle(patch)
            if min(i1 - i0, j1 - j0) * CELL_M < TOP_MIN_SIDE_M or (i1 - i0) * (j1 - j0) * CELL_M * CELL_M < TOP_MIN_M2:
                continue
            tops.append((i0, j0, i1, j1, float(np.median(level[patch & np.isfinite(level)]))))
        # the tops a robot can drive up to come first (a job that names no table takes the first), then by size
        blocked = ~open_floor | (hits >= MIN_HITS)
        reach = int(round(TOP_APPROACH_M / CELL_M))

        def approachable(t):
            i0, j0, i1, j1, _ = t
            strips = (blocked[max(i0 - reach, 0):i0, j0:j1], blocked[i1:i1 + reach, j0:j1],
                      blocked[i0:i1, max(j0 - reach, 0):j0], blocked[i0:i1, j1:j1 + reach])
            return max((1 - float(strip.mean()) for strip in strips if strip.size), default=0.0) >= 0.8
        tops.sort(key=lambda t: (not approachable(t), -(t[2] - t[0]) * (t[3] - t[1])))
        named: dict = {}
        for i0, j0, i1, j1, z in tops:
            xa, xb, ya, yb = (round(float(v), 2) for v in (x0 + j0 * CELL_M, x0 + j1 * CELL_M, y0 + i0 * CELL_M, y0 + i1 * CELL_M))
            room = rooms[int(room_at[(i0 + i1) // 2, (j0 + j1) // 2])]["id"]
            named[room] = named.get(room, 0) + 1
            anchors.append({"id": f"{room}_top_{named[room]}", "room": room, "kind": "surface",
                            "point": [round((xa + xb) / 2, 3), round((ya + yb) / 2, 3), round(floor["z"] + z, 3)],
                            "normal": [0, 0, 1], "source": "mesh",
                            "extent": [[xa, ya], [xb, ya], [xb, yb], [xa, yb]]})
    return {"obstacles": obstacles, "anchors": anchors}
