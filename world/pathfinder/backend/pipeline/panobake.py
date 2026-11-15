"""Texture an untextured scan mesh from posed 360 degree panoramas (Matterport skyboxes).

The Model API serves a model's mesh without UVs or textures, and its panoramas as six cube faces
each with a position and a rotation in the mesh's frame. This gives the mesh a texture atlas (one
patch per triangle) and fills every texel from the panoramas that see it: a depth cube per
panorama (the mesh's own surface, point-splatted) decides who sees what, and nearer, more head-on
views weigh more.

Frames: the mesh frame is metres, Z up. A panorama's local frame is x right, y up, z forward when
looking at face 1; faces 2, 3, 4 follow turning right, 0 is up, 5 down (the layout of
Matterport's quickstart `equirect()`). Which way face 1 looks in the mesh frame is not given by
the API in a usable form, so `solve_headings` finds each panorama's heading from the photos.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

logger = logging.getLogger(__name__)

# face -> (forward, right, down) in the panorama's local frame
FACES = np.array(
    [
        [[0, 1, 0], [1, 0, 0], [0, 0, 1]],
        [[0, 0, 1], [1, 0, 0], [0, -1, 0]],
        [[1, 0, 0], [0, 0, -1], [0, -1, 0]],
        [[0, 0, -1], [-1, 0, 0], [0, -1, 0]],
        [[-1, 0, 0], [0, 0, 1], [0, -1, 0]],
        [[0, -1, 0], [1, 0, 0], [0, 0, -1]],
    ],
    dtype=np.float64,
)
_DEPTH_RES = 256
_MAX_RANGE_M = 14.0


@dataclass
class Pano:
    id: str
    label: str
    position: np.ndarray  # mesh frame
    quat: np.ndarray  # x, y, z, w
    faces: list[Path]  # six images, face 0..5
    to_mesh: np.ndarray = field(default_factory=lambda: np.eye(3))  # local -> mesh frame

    def load(self, size: int | None = None) -> np.ndarray:
        """The six faces as one (6, n, n, 3) uint8 array."""
        out = []
        for path in self.faces:
            with Image.open(path) as im:
                im = im.convert("RGB")
                if size and im.width != size:
                    im = im.resize((size, size), Image.BILINEAR)
                out.append(np.asarray(im))
        return np.stack(out)


def quat_matrix(q: np.ndarray) -> np.ndarray:
    x, y, z, w = q / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def cube_lookup(d: np.ndarray, n: int) -> np.ndarray:
    """Directions (N, 3) in a cube's local frame -> flat pixel index into a (6, n, n) cube."""
    fwd = d @ FACES[:, 0].T  # (N, 6)
    face = fwd.argmax(axis=1)
    f = np.maximum(fwd[np.arange(len(d)), face], 1e-9)
    u = np.einsum("nk,nk->n", d, FACES[face, 1]) / f
    v = np.einsum("nk,nk->n", d, FACES[face, 2]) / f
    col = np.clip(((u + 1) / 2 * n).astype(np.int64), 0, n - 1)
    row = np.clip(((v + 1) / 2 * n).astype(np.int64), 0, n - 1)
    return face * n * n + row * n + col


class Surface:
    """The mesh as an occluder: triangles cut to at most `max_edge` metres, so that one distance
    (to the centroid) describes a whole triangle when sampling it for a viewpoint."""

    def __init__(self, mesh: trimesh.Trimesh, max_edge: float = 0.4):
        v, f = trimesh.remesh.subdivide_to_size(
            np.asarray(mesh.vertices, dtype=np.float64), np.asarray(mesh.faces), max_edge
        )
        tri = v[f]
        self.a, self.e1, self.e2 = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        self.area = np.linalg.norm(np.cross(self.e1, self.e2), axis=1) / 2
        self.centroid = tri.mean(axis=1)
        cross = np.cross(self.e1, self.e2)
        self.normal = cross / np.maximum(np.linalg.norm(cross, axis=1), 1e-12)[:, None]

    def sample_for(self, centre: np.ndarray, count: int, seed: int = 0):
        """`count` surface points spread evenly over the view sphere of `centre`, not over the
        surface: a wall one metre away gets as many points per pixel as one ten metres away.
        Returns the points and the triangle each lies on."""
        rng = np.random.default_rng(seed)
        d2 = np.maximum(((self.centroid - centre) ** 2).sum(axis=1), 0.04)
        p = self.area / d2
        pick = rng.choice(len(p), size=count, p=p / p.sum())
        r1, r2 = np.sqrt(rng.random(count)), rng.random(count)
        points = (
            self.a[pick]
            + (r1 * (1 - r2))[:, None] * self.e1[pick]
            + (r1 * r2)[:, None] * self.e2[pick]
        )
        return points, pick


def depth_cube(surface: Surface, centre: np.ndarray, n: int = _DEPTH_RES) -> np.ndarray:
    """Distance to the nearest surface through every pixel of a mesh-axis-aligned cube around
    `centre` (inf where nothing landed), from about 8 view-uniform samples a pixel."""
    d = surface.sample_for(centre, 8 * 6 * n * n)[0] - centre
    dist = np.linalg.norm(d, axis=1)
    depth = np.full(6 * n * n, np.inf, dtype=np.float32)
    np.minimum.at(depth, cube_lookup(d, n), dist.astype(np.float32))
    return depth


def visible(points: np.ndarray, centre: np.ndarray, depth: np.ndarray, n: int = _DEPTH_RES):
    """(visible mask, distance) of `points` from `centre` against its depth cube."""
    d = points - centre
    dist = np.linalg.norm(d, axis=1)
    seen = dist <= depth[cube_lookup(d, n)] * 1.03 + 0.08
    return seen & (dist < _MAX_RANGE_M) & (dist > 0.05), dist


# ---------------------------------------------------------------------------------- convention


# local (x right, y up, z forward) -> mesh axes with y on +Z, before any turn about Z
_UPRIGHT = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])


def quarter_candidates(quat: np.ndarray) -> list[np.ndarray]:
    """The four local -> mesh matrices a panorama can have: the inverse of its reported rotation
    (tilt included), then 0 to 3 quarter turns about the vertical."""
    r = quat_matrix(quat).T
    out = []
    for quarter in range(4):
        c, s_ = np.cos(quarter * np.pi / 2), np.sin(quarter * np.pi / 2)
        out.append(r @ np.array([[c, -s_, 0], [s_, c, 0], [0, 0, 1.0]]) @ _UPRIGHT)
    return out


def _cube_dirs(n: int) -> np.ndarray:
    """Unit direction through every pixel centre of a (6, n, n) cube, in the cube's frame."""
    jj, ii = np.mgrid[0:n, 0:n]
    u, v = (ii + 0.5) / n * 2 - 1, (jj + 0.5) / n * 2 - 1
    d = np.stack(
        [FACES[k, 0] + u[..., None] * FACES[k, 1] + v[..., None] * FACES[k, 2] for k in range(6)]
    ).reshape(-1, 3)
    return d / np.linalg.norm(d, axis=1)[:, None]


def _mesh_edges(surface: Surface, centre: np.ndarray, n: int) -> np.ndarray:
    """(6, n, n) mask of the mesh's edges seen from `centre`, in an upright cube with no turn:
    where the surface direction changes (wall meets wall, floor or ceiling) or the depth jumps
    (a door frame against the room behind it)."""
    points, tri = surface.sample_for(centre, 10 * 6 * n * n)
    d = points - centre
    dist = np.linalg.norm(d, axis=1).astype(np.float32)
    pixel = cube_lookup(d @ _UPRIGHT, n)
    order = np.argsort(-dist)  # far first: the nearest sample wins its pixel
    depth = np.full(6 * n * n, np.inf, np.float32)
    kind = np.full(6 * n * n, -1, np.int8)
    depth[pixel[order]] = dist[order]
    kind[pixel[order]] = np.abs(surface.normal[tri]).argmax(axis=1).astype(np.int8)[order]
    depth, kind = depth.reshape(6, n, n), kind.reshape(6, n, n)
    # a pixel the near wall's samples missed shows the room behind: take, in each 3 x 3 window,
    # the nearest surface, twice
    for _ in range(2):
        pad_d = np.pad(depth, ((0, 0), (1, 1), (1, 1)), constant_values=np.inf)
        pad_k = np.pad(kind, ((0, 0), (1, 1), (1, 1)), constant_values=-1)
        stack_d = np.stack([pad_d[:, i : i + n, j : j + n] for i in range(3) for j in range(3)])
        stack_k = np.stack([pad_k[:, i : i + n, j : j + n] for i in range(3) for j in range(3)])
        nearest = stack_d.argmin(axis=0)
        depth = np.take_along_axis(stack_d, nearest[None], axis=0)[0]
        kind = np.take_along_axis(stack_k, nearest[None], axis=0)[0]
    edge = np.zeros(kind.shape, dtype=bool)
    for axis in (1, 2):
        a_k, b_k = np.moveaxis(kind, axis, 0)[1:], np.moveaxis(kind, axis, 0)[:-1]
        a_d, b_d = np.moveaxis(depth, axis, 0)[1:], np.moveaxis(depth, axis, 0)[:-1]
        jump = (a_k != b_k) | (np.abs(a_d - b_d) > 0.12 * np.minimum(a_d, b_d) + 0.05)
        np.moveaxis(edge, axis, 0)[1:] |= jump & np.isfinite(a_d) & np.isfinite(b_d)
    return edge


def solve_headings(mesh: trimesh.Trimesh, panos: list[Pano], size: int = 256) -> dict:
    """Set every panorama's `to_mesh`.

    Measured on the 2026 hackathon set: face 1 of a skybox looks along minus the reported turn
    about Z, plus a whole number of quarter turns that the API does not give and that differs
    between panoramas. So each has four candidates, and its own photo picks: the mesh's edges
    (corners, door frames, where walls meet the floor and ceiling), projected into the photo,
    must land on edges in the photo. Each panorama is solved alone, so one bad photo cannot
    mislead its neighbours.

    Returns the quarter turns chosen and each panorama's margin (how far the winner's edge
    score is above the runner-up's; under 0.03 is listed as weak, a coin toss).
    """
    surface = Surface(mesh)
    dirs = _cube_dirs(size)
    horizon = np.abs(dirs[:, 1]) < 0.8  # straight up and down say nothing about heading
    choice, margins = [], []
    for p in panos:
        grey = p.load(size).astype(np.float32).mean(axis=3)
        grad = np.zeros_like(grey)
        grad[:, :, 1:-1] += np.abs(grey[:, :, 2:] - grey[:, :, :-2])
        grad[:, 1:-1, :] += np.abs(grey[:, 2:, :] - grey[:, :-2, :])
        grad = np.minimum(grad, np.percentile(grad, 99)).reshape(-1)  # lamps, window glare
        edge_dirs = dirs[_mesh_edges(surface, p.position, size).reshape(-1) & horizon]
        upright_inv = _UPRIGHT.T
        scores = []
        for to_mesh in quarter_candidates(p.quat):
            # edge directions are in the no-turn upright cube: mesh frame, then this candidate
            local = (edge_dirs @ upright_inv) @ to_mesh
            scores.append(float(grad[cube_lookup(local, size)].mean()))
        scores = np.array(scores) / max(float(grad[horizon].mean()), 1e-9)
        best = int(scores.argmax())
        choice.append(best)
        margins.append(float((scores[best] - np.partition(scores, -2)[-2]) / scores[best]))
        p.to_mesh = quarter_candidates(p.quat)[best]
    choice, margins = np.array(choice), np.array(margins)
    report = {
        "quarter_turns": {p.label: int(k) for p, k in zip(panos, choice)},
        "counts": {str(k): int((choice == k).sum()) for k in range(4)},
        "median_margin": round(float(np.median(margins)), 3),
        "weak": [p.label for p, m in zip(panos, margins) if m < 0.03],
    }
    logger.info("pano headings: %s, %d weak", report["counts"], len(report["weak"]))
    return report


# --------------------------------------------------------------------------------------- atlas


def _face_frames(mesh: trimesh.Trimesh):
    """Per triangle: corner A, in-plane unit axes X (along AB) and Y, and the 2D corners."""
    tri = np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.faces)]
    a, e1, e2 = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    length = np.linalg.norm(e1, axis=1)
    x = e1 / np.maximum(length, 1e-12)[:, None]
    normal = np.cross(e1, e2)
    area2 = np.linalg.norm(normal, axis=1)
    normal /= np.maximum(area2, 1e-12)[:, None]
    y = np.cross(normal, x)
    cx, cy = np.einsum("fk,fk->f", e2, x), np.einsum("fk,fk->f", e2, y)
    xmin = np.minimum(0.0, cx)
    width = np.maximum(length, cx) - xmin
    return a, x, y, normal, length, cx, cy, xmin, width, area2 > 1e-10


def _shelf_pack(w: np.ndarray, h: np.ndarray, size: int):
    """Left-to-right rows, tallest first. Returns (x, y) per box, or None if it overflows."""
    order = np.argsort(-h, kind="stable")
    ox, oy = np.zeros(len(w), int), np.zeros(len(w), int)
    cur_x = cur_y = row_h = 0
    for i in order:
        if cur_x + w[i] > size:
            cur_x, cur_y, row_h = 0, cur_y + row_h, 0
        if cur_y + h[i] > size:
            return None
        ox[i], oy[i] = cur_x, cur_y
        cur_x += w[i]
        row_h = max(row_h, h[i])
    return ox, oy


def bake(
    mesh: trimesh.Trimesh,
    panos: list[Pano],
    *,
    atlas_size: int = 4096,
    max_density: float = 160.0,
    pad: int = 2,
) -> tuple[trimesh.Trimesh, dict]:
    """`mesh` with one texture patch per triangle, coloured from `panos` (their `to_mesh` set).
    Returns the textured mesh (unwelded: three vertices a face) and stats."""
    a, x, y, normal, length, cx, cy, xmin, width, ok = _face_frames(mesh)
    faces = np.flatnonzero(ok)

    def boxes(density):
        return (
            np.ceil(width[faces] * density).astype(int) + 2 * pad,
            np.ceil(cy[faces] * density).astype(int) + 2 * pad,
        )

    lo, hi, packed, density = 4.0, max_density, None, max_density
    for step in range(18):  # the densest patches that still fit: try the cap, then bisect
        mid = hi if step == 0 else (lo + hi) / 2
        w, h = boxes(mid)
        trial = _shelf_pack(w, h, atlas_size) if w.max() <= atlas_size else None
        if trial is None:
            hi = mid
        else:
            lo, packed, density = mid, (trial, w, h), mid
            if step == 0:
                break
    if packed is None:
        raise ValueError("the mesh does not fit the atlas even at 4 px/m")
    (ox, oy), w, h = packed

    # every texel of every patch: its atlas pixel and the 3D point under it (the patch's padding
    # extends the triangle's plane, so bilinear filtering never reads an unwritten texel)
    pix, pts, nrm = [], [], []
    for k, f in enumerate(faces):
        jj, ii = np.mgrid[0 : h[k], 0 : w[k]]
        px = (ii.ravel() + 0.5 - pad) / density + xmin[f]
        py = (jj.ravel() + 0.5 - pad) / density
        pts.append((a[f] + px[:, None] * x[f] + py[:, None] * y[f]).astype(np.float32))
        pix.append(((oy[k] + jj.ravel()) * atlas_size + ox[k] + ii.ravel()).astype(np.int64))
        nrm.append(np.full(len(px), f, dtype=np.int32))
    pix, pts, nrm = np.concatenate(pix), np.concatenate(pts), np.concatenate(nrm)
    logger.info("atlas: %d patches, %.0f px/m, %.1f M texels", len(faces), density, len(pix) / 1e6)

    surface = Surface(mesh)
    acc = np.zeros((len(pix), 3), np.float32)
    weight = np.zeros(len(pix), np.float32)
    acc_any = np.zeros((len(pix), 3), np.float32)  # fallback for texels no pano sees
    weight_any = np.zeros(len(pix), np.float32)
    chunk = 1_500_000
    for p in panos:
        depth = depth_cube(surface, p.position)
        cube = p.load()
        n = cube.shape[1]
        cube = cube.reshape(-1, 3)
        for s in range(0, len(pix), chunk):
            sl = slice(s, s + chunk)
            seen, dist = visible(pts[sl].astype(np.float64), p.position, depth)
            d = pts[sl].astype(np.float64) - p.position
            facing = np.abs(np.einsum("nk,nk->n", d, normal[nrm[sl]])) / np.maximum(dist, 1e-6)
            score = (facing / (dist + 0.5) ** 2).astype(np.float32)
            near = dist < _MAX_RANGE_M
            colour = cube[cube_lookup(d @ p.to_mesh, n)].astype(np.float32)
            w_seen = np.where(seen, score, 0) ** 4
            w_any = np.where(near, score, 0) ** 4
            acc[sl] += colour * w_seen[:, None]
            weight[sl] += w_seen
            acc_any[sl] += colour * w_any[:, None]
            weight_any[sl] += w_any
    unseen = weight <= 0
    acc[unseen], weight[unseen] = acc_any[unseen], weight_any[unseen]
    blank = weight <= 0
    colour = np.where(blank[:, None], 128.0, acc / np.maximum(weight, 1e-20)[:, None])

    image = np.full((atlas_size * atlas_size, 3), 128, np.uint8)
    image[pix] = colour.clip(0, 255).astype(np.uint8)
    atlas = Image.fromarray(image.reshape(atlas_size, atlas_size, 3))

    # one vertex per face corner, with its patch's UV (v = 1 is the image's top row)
    tri = np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.faces)[faces]]
    corners_x = np.stack([np.zeros(len(faces)), length[faces], cx[faces]], axis=1)
    corners_y = np.stack([np.zeros(len(faces)), np.zeros(len(faces)), cy[faces]], axis=1)
    u = ((corners_x - xmin[faces, None]) * density + pad + ox[:, None]) / atlas_size
    v = 1.0 - (corners_y * density + pad + oy[:, None]) / atlas_size
    out = trimesh.Trimesh(
        tri.reshape(-1, 3), np.arange(len(faces) * 3).reshape(-1, 3), process=False
    )
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=atlas, metallicFactor=0.0, roughnessFactor=1.0
    )
    out.visual = trimesh.visual.TextureVisuals(
        uv=np.stack([u.ravel(), v.ravel()], axis=1), image=atlas, material=material
    )
    stats = {
        "patches": len(faces),
        "px_per_m": round(density, 1),
        "texels": len(pix),
        "seen_pct": round(100 * float(1 - unseen.mean()), 1),
        "blank_pct": round(100 * float(blank.mean()), 2),
    }
    return out, stats
