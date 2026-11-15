"""Occupancy grid at 0.05 m cells.

`Grid` is just origin + cell + a boolean array, so a mesh slice can supply the
array later. `from_world` is the stand-in builder: room polygons, doorway gaps
and obstacle boxes. A cell is occupied if a wall touches its square; at the
two ends of a doorway gap a cell is occupied only if its centre is in the solid
part, so a gap comes out within one cell of the stated width, unbiased.
Clearance is measured to occupied cell centres.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from .building import OUTSIDE, passable_doorways

CELL_M = 0.05
PREPASS_BAND_M = (0.05, 1.0)
APRON_DEPTH_M = 1.2   # free floor carved beyond a doorway that leads outside
APRON_SIDE_M = 0.6
WAY_OUT_STEP_M = 0.6  # how far past the way-out doorway the delivery point is


@dataclass
class Grid:
    origin: tuple[float, float]
    cell: float
    occ: np.ndarray  # [row = y, col = x], True = occupied
    _clear: np.ndarray | None = field(default=None, repr=False)

    @property
    def clearance(self) -> np.ndarray:
        """Metres from each cell centre to the nearest occupied cell centre."""
        if self._clear is None:
            padded = np.pad(self.occ, 1, constant_values=True)
            self._clear = ndimage.distance_transform_edt(~padded)[1:-1, 1:-1] * self.cell
        return self._clear

    def index(self, x, y):
        j = np.floor((np.asarray(x, float) - self.origin[0]) / self.cell + 1e-9).astype(int)
        i = np.floor((np.asarray(y, float) - self.origin[1]) / self.cell + 1e-9).astype(int)
        return i, j

    def centre(self, i, j):
        return (self.origin[0] + (np.asarray(j) + 0.5) * self.cell,
                self.origin[1] + (np.asarray(i) + 0.5) * self.cell)

    def inside(self, i, j):
        return (i >= 0) & (j >= 0) & (i < self.occ.shape[0]) & (j < self.occ.shape[1])

    def occupied_at(self, x, y) -> np.ndarray:
        i, j = self.index(x, y)
        ok = self.inside(i, j)
        out = np.ones(np.shape(i), bool)
        out[ok] = self.occ[i[ok], j[ok]]
        return out

    def clearance_at(self, x, y) -> np.ndarray:
        i, j = self.index(x, y)
        ok = self.inside(i, j)
        out = np.zeros(np.shape(i), float)
        out[ok] = self.clearance[i[ok], j[ok]]
        return out

    def free_mask(self, radius_m: float) -> np.ndarray:
        """Cells where a disc of that radius fits."""
        return (self.clearance >= radius_m - 1e-9) & ~self.occ

    def nearest_in(self, mask: np.ndarray, x: float, y: float, within_m: float):
        """Cell of `mask` nearest (x, y), no farther than within_m, or None."""
        i0, j0 = (int(v) for v in self.index(x, y))
        r = int(math.ceil(within_m / self.cell)) + 1
        best, best_d = None, within_m + 1e-9
        for i in range(max(0, i0 - r), min(mask.shape[0], i0 + r + 1)):
            for j in range(max(0, j0 - r), min(mask.shape[1], j0 + r + 1)):
                if mask[i, j]:
                    cx, cy = self.centre(i, j)
                    d = math.hypot(cx - x, cy - y)
                    if d < best_d:
                        best, best_d = (i, j), d
        return best

    def reachable(self, radius_m: float, x: float, y: float, snap_m: float = 0.15):
        """Mask of cells a disc of radius_m can reach from (x, y), or None."""
        mask = self.free_mask(radius_m)
        seed = self.nearest_in(mask, x, y, snap_m)
        if seed is None:
            return None
        labels, _ = ndimage.label(mask)  # 4-connected, like the planner (no corner cutting)
        return labels == labels[seed]


def points_in_polygon(px, py, polygon) -> np.ndarray:
    inside = np.zeros(np.shape(px), bool)
    n = len(polygon)
    for k in range(n):
        x1, y1 = polygon[k][0], polygon[k][1]
        x2, y2 = polygon[(k + 1) % n][0], polygon[(k + 1) % n][1]
        if y1 == y2:
            continue
        cross = ((y1 > py) != (y2 > py)) & (px < (x2 - x1) * (py - y1) / (y2 - y1) + x1)
        inside ^= cross
    return inside


def _mark_segment(occ, cx, cy, a, b, cell, square_a=False, square_b=False):
    """Occupy every cell whose square the segment a-b touches.

    A square end (a doorway jamb) stops at the end: only cells whose centre
    projects onto the segment are taken there.
    """
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return
    raw = ((cx - ax) * dx + (cy - ay) * dy) / L2
    t = np.clip(raw, 0.0, 1.0)
    dist = np.hypot(cx - (ax + t * dx), cy - (ay + t * dy))
    hit = dist <= cell * math.sqrt(0.5) + 1e-9
    if square_a:
        hit &= raw >= 0.0
    if square_b:
        hit &= raw <= 1.0
    occ |= hit


def door_frame(door: dict):
    """(position, unit along, unit normal) of a doorway."""
    p = np.array(door["position"][:2], float)
    u = np.array(door["along"][:2], float)
    u = u / (np.linalg.norm(u) or 1.0)
    return p, u, np.array([-u[1], u[0]])


def outward_normal(door: dict, rooms_by_id: dict):
    """Unit normal of the doorway pointing from rooms[1]... away from the inner room.

    For a doorway to outside that is out of the building; otherwise it points
    from the first room listed into the second.
    """
    p, _, n = door_frame(door)
    a, b = door["rooms"]
    inner = b if a == OUTSIDE else a
    room = rooms_by_id.get(inner)
    if room is None:
        return n
    c = np.mean(np.array(room["polygon"], float)[:, :2], axis=0)
    return n if np.dot(p - c, n) >= 0 else -n


def way_out_point(world: dict):
    """([x, y, yaw], doorway) just past the way-out doorway, or (None, None)."""
    door_id = (world.get("way_out") or {}).get("doorway")
    door = next((d for d in passable_doorways(world) if d["id"] == door_id), None)
    if door is None:
        return None, None
    rooms = {r["id"]: r for r in world["rooms"]}
    p, _, _ = door_frame(door)
    n = outward_normal(door, rooms)
    g = p + n * WAY_OUT_STEP_M
    return [float(g[0]), float(g[1]), float(math.atan2(n[1], n[0]))], door


GROUND_STEP_M = 0.15  # ground standing higher than this above the bare ground is not driven over (a kerb is about 0.12 m)
_rasters: dict = {}


def ground_raster(world: dict):
    """(height, water, [x0, y0, x1, y1]) of the surveyed ground the world lies on, or None. `ground.height` in
    world.json names an .npz in the repo: `height` in metres above the bare ground and `water` (open water),
    one value per pixel of the aerial photo, row 0 at the north edge, covering `ground.extent`."""
    from pathlib import Path

    g = world.get("ground") or {}
    if not g.get("height"):
        return None
    path = Path(__file__).resolve().parents[1] / g["height"]
    key = (str(path), path.stat().st_mtime)
    if key not in _rasters:
        z = np.load(path)
        _rasters.clear()
        _rasters[key] = (z["height"].astype(np.float32), z["water"].astype(bool))
    return (*_rasters[key], [float(v) for v in g["extent"]])


def ground_blocked(world: dict, x, y) -> np.ndarray:
    """True where the survey shows something standing on the ground at (x, y), or open water, or nothing at all
    (outside the survey). The survey sees the top of things only: ground under a tree's canopy counts as blocked."""
    got = ground_raster(world)
    x, y = np.asarray(x, float), np.asarray(y, float)
    if got is None:
        return np.zeros(x.shape, bool)
    height, water, (x0, y0, x1, y1) = got
    rows, cols = height.shape
    j = np.floor((x - x0) / (x1 - x0) * cols).astype(int)
    i = np.floor((y1 - y) / (y1 - y0) * rows).astype(int)
    inside = (i >= 0) & (i < rows) & (j >= 0) & (j < cols)
    i, j = np.clip(i, 0, rows - 1), np.clip(j, 0, cols - 1)
    return ~inside | (height[i, j] > GROUND_STEP_M) | water[i, j]


def from_world(world: dict, z_band=PREPASS_BAND_M, *, cell: float = CELL_M, pad_m: float = 1.5, ground: bool = True) -> Grid:
    """Grid from room polygons, doorway gaps and the obstacle boxes overlapping z_band, and, when the world lies
    on surveyed ground (`ground.height`), whatever that survey shows standing on it (`ground=False` leaves it out).

    Everything outside every room is occupied, except a small apron beyond each
    doorway that leads outside (so the way out can be driven through). Every
    polygon edge is a wall; passable doorways cut a gap of their width in it.
    `world["mesh"]` is not read: a mesh slice would build the same Grid.
    """
    rooms = world["rooms"]
    rooms_by_id = {r["id"]: r for r in rooms}
    pts = np.array([p[:2] for r in rooms for p in r["polygon"]], float)
    x0 = math.floor((pts[:, 0].min() - pad_m) / cell) * cell
    y0 = math.floor((pts[:, 1].min() - pad_m) / cell) * cell
    nx = int(math.ceil((pts[:, 0].max() + pad_m - x0) / cell))
    ny = int(math.ceil((pts[:, 1].max() + pad_m - y0) / cell))
    grid = Grid((x0, y0), cell, np.ones((ny, nx), bool))
    jj, ii = np.meshgrid(np.arange(nx), np.arange(ny))
    cx, cy = grid.centre(ii, jj)

    free = np.zeros((ny, nx), bool)
    for r in rooms:
        free |= points_in_polygon(cx, cy, r["polygon"])
    doors = passable_doorways(world)
    for d in doors:
        if OUTSIDE in d["rooms"]:
            p, u, _ = door_frame(d)
            n = outward_normal(d, rooms_by_id)
            s = (cx - p[0]) * u[0] + (cy - p[1]) * u[1]
            t = (cx - p[0]) * n[0] + (cy - p[1]) * n[1]
            free |= (np.abs(s) <= d["width_m"] / 2 + APRON_SIDE_M) & (t > 0) & (t <= APRON_DEPTH_M)
    occ = ~free

    for r in rooms:
        poly = [np.array(p[:2], float) for p in r["polygon"]]
        for k in range(len(poly)):
            a, b = poly[k], poly[(k + 1) % len(poly)]
            L = float(np.linalg.norm(b - a))
            if L < 1e-9:
                continue
            e = (b - a) / L
            gaps = []
            for d in doors:
                p, u, _ = door_frame(d)
                s = float(np.dot(p - a, e))
                off = abs(float((p - a)[0] * e[1] - (p - a)[1] * e[0]))
                if off <= 0.1 and abs(float(np.dot(u, e))) > 0.9 and -1e-6 <= s <= L + 1e-6:
                    gaps.append((s - d["width_m"] / 2, s + d["width_m"] / 2))
            at, cut = 0.0, False
            for g0, g1 in sorted(gaps):
                if g0 > at:
                    _mark_segment(occ, cx, cy, a + e * at, a + e * min(g0, L), cell, cut, g0 < L)
                if g1 > at:
                    at, cut = g1, True
            if at < L:
                _mark_segment(occ, cx, cy, a + e * at, b, cell, cut, False)

    lo, hi = z_band
    for o in world.get("obstacles", []):
        mn, mx = o["box"]["min"], o["box"]["max"]
        if mn[2] < hi and mx[2] > lo:
            h = cell / 2 + 1e-9
            occ |= (cx >= mn[0] - h) & (cx <= mx[0] + h) & (cy >= mn[1] - h) & (cy <= mx[1] + h)
    if ground and (world.get("ground") or {}).get("height"):
        occ |= ground_blocked(world, cx, cy)
    grid.occ = occ
    return grid


def from_mesh(mesh_path: str, z_band, *, cell: float = CELL_M) -> Grid:
    """Slice the scan mesh between z_band and project down. Not implemented."""
    raise NotImplementedError("mesh slicing is not implemented; nav uses from_world")


def footprint_samples(polygon, step: float) -> np.ndarray:
    """Points covering a footprint polygon (edges and interior) in the body frame."""
    poly = np.array([p[:2] for p in polygon], float)
    pts = []
    for k in range(len(poly)):
        a, b = poly[k], poly[(k + 1) % len(poly)]
        n = max(1, int(math.ceil(np.linalg.norm(b - a) / step)))
        pts.append(a + (b - a) * np.linspace(0, 1, n, endpoint=False)[:, None])
    xs = np.arange(poly[:, 0].min(), poly[:, 0].max() + step, step)
    ys = np.arange(poly[:, 1].min(), poly[:, 1].max() + step, step)
    gx, gy = np.meshgrid(xs, ys)
    keep = points_in_polygon(gx.ravel(), gy.ravel(), poly)
    pts.append(np.column_stack([gx.ravel()[keep], gy.ravel()[keep]]))
    return np.vstack(pts)


def placed(samples: np.ndarray, x, y, yaw):
    """World x, y of body-frame samples at one or many poses (broadcast on leading axes)."""
    x, y, yaw = (np.asarray(v, float)[..., None] for v in (x, y, yaw))
    c, s = np.cos(yaw), np.sin(yaw)
    return x + c * samples[:, 0] - s * samples[:, 1], y + s * samples[:, 0] + c * samples[:, 1]


def base_geometry(build: dict):
    """(footprint polygon, inscribed radius, circumscribed radius) from build.json."""
    base = build["base"]
    poly = np.array([p[:2] for p in base["footprint"]], float)
    r_out = base.get("circumscribed_radius_m")
    if not isinstance(r_out, (int, float)):
        r_out = float(np.hypot(poly[:, 0], poly[:, 1]).max())
    r_in = base.get("inscribed_radius_m")
    if not isinstance(r_in, (int, float)):
        d = []
        for k in range(len(poly)):
            a, b = poly[k], poly[(k + 1) % len(poly)]
            d.append(abs(a[0] * b[1] - a[1] * b[0]) / (np.linalg.norm(b - a) or 1.0))
        r_in = float(min(d))
    return poly, float(r_in), float(r_out)
