"""Import a finished textured mesh as a scene package: a Matterport MatterPak OBJ, the Matterport
API mesh baked from its panoramas, or the block model `pipeline.vexcel` builds.

The source is already metric and textured, so this only has to put the mesh in the package frame
(metres, +Y up, origin on the ground under the middle of the scan), fit it to the headset's
triangle and texture budgets, and publish `mesh.r<rev>.glb`, `collision.r<rev>.glb`, an empty
`cameras.r<rev>.json` and `scene.json`.

What an imported package does not have: source photos with poses (`thumbs/` and the cameras
list are empty, unless Matterport panoramas posed them) and no structure or parts layers. The
headset falls back to mesh snapping; server features that read the photos answer "not ready".
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage

from pipeline.calibrate import ScaleEstimate
from pipeline.mesh import (
    _ensure_jpeg_texture,
    _merge_atlases,
    _tight_crop_scene_textures,
    build_collision_mesh,
    decimate_textured,
)
from pipeline.package import (
    Camera,
    load_or_create_frame_id,
    make_thumbs,
    publish_revision,
    recommended_spawn,
    revision_filenames,
    validate_package,
    write_cameras_json,
    write_json_atomic,
)

logger = logging.getLogger(__name__)

UNITS_M = {"m": 1.0, "cm": 0.01, "mm": 0.001, "ft": 0.3048, "usft": 1200 / 3937, "in": 0.0254}
_EYE_M = 1.6
_CELL_M = 0.25  # floor grid for the interior spawn
_FLAT = 0.9  # |normal . up| above this is a floor, ceiling, roof or the ground


@dataclass
class SourceView:
    """A photo with a known pinhole pose in the source mesh's frame and units: where it was taken
    and the unit vectors of its image axes (right, down) and its optical axis (forward)."""

    image: Path
    position: np.ndarray
    right: np.ndarray
    down: np.ndarray
    forward: np.ndarray
    fov_deg: float = 90.0


def _axes(v: np.ndarray, up: str) -> np.ndarray:
    """A source-frame direction (or centred point) in the package's axes."""
    v = np.asarray(v, dtype=np.float64)
    return np.array([v[0], v[2], -v[1]]) if up == "z" else v


def package_cameras(
    views: list[SourceView], out_dir: Path, up: str, unit_m: float, origin: list
) -> list[Camera]:
    """Write `thumbs/` for the views and return their cameras in the package frame."""
    make_thumbs([v.image for v in views], Path(out_dir) / "thumbs")
    cameras = []
    for v in views:
        with Image.open(v.image) as im:
            w, h = im.size
        R = np.stack([_axes(v.right, up), _axes(v.down, up), _axes(v.forward, up)])
        position = _axes((np.asarray(v.position, dtype=np.float64) - origin) * unit_m, up)
        f = (w / 2) / np.tan(np.radians(v.fov_deg) / 2)
        thumb = f"thumbs/{Path(v.image).with_suffix('.jpg').name}"
        cameras.append(
            Camera(id=Path(v.image).stem, file=thumb, thumb=thumb, R=R, t=-R @ position,
                   fx=f, fy=f, cx=w / 2, cy=h / 2, w=w, h=h)
        )  # fmt: skip
    return cameras


def load_scene(src: Path) -> trimesh.Scene:
    """The source mesh as a scene of textured pieces, node transforms applied (a GLB's Y-up node
    rotation, a tile's placement)."""
    scene = trimesh.load(src, force="scene", process=False)
    pieces = [g for g in scene.dump() if isinstance(g, trimesh.Trimesh) and len(g.faces)]
    if not pieces:
        raise ValueError(f"{src} has no triangles (a point cloud needs meshing first)")
    for g in pieces:  # an OBJ's MTL loads as a SimpleMaterial; the mesh helpers read PBR ones
        material = getattr(g.visual, "material", None)
        if hasattr(material, "to_pbr"):
            g.visual.material = material.to_pbr()
    return trimesh.Scene(pieces)


def _face_areas_normals(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    tri = np.asarray(mesh.vertices)[np.asarray(mesh.faces)]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(cross, axis=1)
    return norm / 2.0, cross / np.maximum(norm, 1e-12)[:, None]


def guess_up(scene: trimesh.Scene) -> str:
    """'y' or 'z': the axis most of the flat area faces (floors, ceilings, roofs, the ground).
    A guess: a corridor with more wall than floor can fool it, so `--up` overrides."""
    flat = np.zeros(3)
    for g in scene.geometry.values():
        area, normal = _face_areas_normals(g)
        flat += (area[:, None] * (np.abs(normal) > _FLAT)).sum(axis=0)
    return "z" if flat[2] > flat[1] else "y"


def crop_bbox(scene: trimesh.Scene, bbox: tuple[float, float, float, float], up: str) -> None:
    """Keep the faces whose centroid is inside `bbox` = (min_a, min_b, max_a, max_b) over the
    source file's two horizontal axes, in its own units: x and y for a Z-up file (easting and
    northing for a georeferenced tile), x and z for a Y-up one. In place."""
    a, b = (0, 1) if up == "z" else (0, 2)
    lo, hi = np.array(bbox[:2]), np.array(bbox[2:])
    for name in list(scene.geometry):
        g = scene.geometry[name]
        centroid = g.triangles_center[:, [a, b]]
        keep = np.all((centroid >= lo) & (centroid <= hi), axis=1)
        if not keep.any():
            scene.delete_geometry(name)
        elif not keep.all():
            g.update_faces(keep)
            g.remove_unreferenced_vertices()
    if not scene.geometry:
        raise ValueError(f"nothing inside --bbox {bbox}: the scan spans {scene.bounds}")


def to_package_frame(vertices: np.ndarray, up: str, unit_m: float) -> tuple[np.ndarray, list]:
    """Source coordinates -> package frame (metres, right-handed, +Y up, horizontal centre of the
    bounding box at x = z = 0, lowest point at y = 0). Returns the points and the source-unit
    point that became the origin (what a georeferenced tile needs to go back to map coordinates).
    Float64 throughout: UTM eastings lose centimetres in float32."""
    v = np.asarray(vertices, dtype=np.float64)
    lo, hi = v.min(axis=0), v.max(axis=0)
    origin = (lo + hi) / 2.0
    k = 2 if up == "z" else 1
    origin[k] = lo[k]
    v = (v - origin) * unit_m
    if up == "z":  # (x, y, z) -> (x, z, -y): a rotation, so the mesh keeps its handedness
        v = np.c_[v[:, 0], v[:, 2], -v[:, 1]]
    return v, origin.tolist()


def is_interior(mesh: trimesh.Trimesh) -> bool:
    """A room scan has ceilings: about as much area facing down as up. An aerial mesh has next to
    none, the camera never saw the underside of anything."""
    area, normal = _face_areas_normals(mesh)
    up_area = area[normal[:, 1] > _FLAT].sum()
    down_area = area[normal[:, 1] < -_FLAT].sum()
    return bool(up_area > 0 and down_area > 0.3 * up_area)


def interior_spawn(mesh: trimesh.Trimesh) -> dict | None:
    """Stand in the most open spot of the biggest floor: the floor cell farthest from any cell
    without floor (walls, furniture, the outside), eyes 1.6 m above it, facing the middle of that
    floor. None when no floor is found."""
    area, normal = _face_areas_normals(mesh)
    centre = mesh.triangles_center
    floor = normal[:, 1] > _FLAT
    if not floor.any():
        return None
    # the biggest level: the 10 cm height band holding the most upward-facing area
    y = centre[floor, 1]
    bins = np.floor((y - y.min()) / 0.1).astype(int)
    level = y.min() + (np.bincount(bins, weights=area[floor]).argmax() + 0.5) * 0.1
    on_level = floor & (np.abs(centre[:, 1] - level) < 0.15)

    lo = mesh.bounds[0, [0, 2]]
    shape = np.ceil((mesh.bounds[1, [0, 2]] - lo) / _CELL_M).astype(int) + 3  # 1-cell empty rim
    grid = np.zeros(shape, dtype=bool)
    # points spread over the floor by area (about 16 a cell), so a decimated floor's few big
    # triangles fill their cells as well as a dense scan's many small ones
    tri = np.asarray(mesh.vertices)[np.asarray(mesh.faces)[on_level]][:, :, [0, 2]]
    floor_area = area[on_level]
    rng = np.random.default_rng(0)
    n = int(np.clip(16 * floor_area.sum() / _CELL_M**2, 1_000, 4_000_000))
    pick = rng.choice(len(tri), size=n, p=floor_area / floor_area.sum())
    r1, r2 = np.sqrt(rng.random(n)), rng.random(n)
    bary = np.c_[1 - r1, r1 * (1 - r2), r1 * r2]
    pts = np.einsum("nk,nkd->nd", bary, tri[pick])
    ij = np.floor((pts - lo) / _CELL_M).astype(int) + 1
    grid[ij[:, 0], ij[:, 1]] = True
    grid = ndimage.binary_closing(grid, iterations=2)
    # anything standing on the floor (furniture, walls) between ankle and head height blocks a cell
    body = (centre[:, 1] > level + 0.2) & (centre[:, 1] < level + 1.9)
    bj = np.floor((centre[body][:, [0, 2]] - lo) / _CELL_M).astype(int) + 1
    grid[bj[:, 0], bj[:, 1]] = False

    clearance = ndimage.distance_transform_edt(grid)
    if clearance.max() <= 0:
        return None
    i, j = np.unravel_index(clearance.argmax(), clearance.shape)
    pos = np.array([lo[0] + (i - 0.5) * _CELL_M, level + _EYE_M, lo[1] + (j - 0.5) * _CELL_M])
    cells = np.argwhere(grid)
    mid = lo + (cells.mean(axis=0) - 0.5) * _CELL_M
    look = np.array([mid[0], level + _EYE_M, mid[1]])
    if np.linalg.norm(look - pos) < 0.5:  # already standing in the middle: face the long way
        span = mesh.bounds[1] - mesh.bounds[0]
        look = pos + (np.array([1.0, 0, 0]) if span[0] >= span[2] else np.array([0, 0, 1.0]))
    return {"pos": pos.tolist(), "look": look.tolist()}


def import_mesh(
    src: Path,
    site: str,
    out_dir: Path,
    work_dir: Path,
    *,
    source: str = "mesh",
    up: str = "auto",
    unit: str = "m",
    scale: float = 1.0,
    bbox: tuple[float, float, float, float] | None = None,
    spawn: str = "auto",
    views: list[SourceView] | None = None,
    target_triangles: int = 200_000,
    collision_triangles: int = 50_000,
    max_texture_size: int = 4096,
) -> dict:
    """`src` (OBJ + MTL + textures, GLB/glTF, PLY) -> scene package in `out_dir`, published as
    the next revision. `unit` x `scale` is metres per source unit. `views` (photos posed in the
    source frame) become the package's cameras and thumbs. Returns a report; its
    `problems` list is `validate_package`'s (empty = the headset can load it as is)."""
    src, out_dir, work_dir = Path(src), Path(out_dir), Path(work_dir)
    if unit not in UNITS_M:
        raise ValueError(f"unknown unit {unit!r}: one of {', '.join(UNITS_M)}")
    unit_m = UNITS_M[unit] * scale
    scene = load_scene(src)
    pieces_in = len(scene.geometry)
    triangles_in = int(sum(len(g.faces) for g in scene.geometry.values()))

    if up == "auto":
        up = "y" if src.suffix.lower() in (".glb", ".gltf") else guess_up(scene)
    if up not in ("y", "z"):
        raise ValueError(f"--up must be auto, y or z, not {up!r}")
    if bbox is not None:
        crop_bbox(scene, bbox, up)

    mesh = _merge_atlases(_tight_crop_scene_textures(scene))
    mesh.vertices, origin = to_package_frame(mesh.vertices, up, unit_m)
    mesh = decimate_textured(mesh, target_triangles)
    mesh = _ensure_jpeg_texture(mesh, max_texture_size)
    collision = build_collision_mesh(mesh, collision_triangles)

    previous = None
    try:
        previous = json.loads((out_dir / "scene.json").read_text())
    except (OSError, json.JSONDecodeError):
        pass
    revision = int((previous or {}).get("revision", 0)) + 1
    names = revision_filenames(revision)
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh.export(out_dir / names["mesh"])
    collision.export(out_dir / names["collision"])
    cameras = package_cameras(views, out_dir, up, unit_m, origin) if views else []
    if cameras:
        write_cameras_json(cameras, out_dir / names["cameras"])
    else:
        write_json_atomic(out_dir / names["cameras"], "[]")

    interior = is_interior(mesh) if spawn == "auto" else spawn == "inside"
    where = None
    if interior and cameras:  # somebody stood there to take the photo: the most central one
        spots = np.array([c.position for c in cameras])
        pos = spots[np.linalg.norm(spots - np.median(spots, axis=0), axis=1).argmin()]
        away = spots[np.linalg.norm(spots - pos, axis=1).argmax()]
        where = {"pos": pos.tolist(), "look": [away[0], pos[1], away[2]]}
    elif interior:
        where = interior_spawn(mesh)
    where = where or recommended_spawn(mesh.bounds, cameras)

    image = getattr(getattr(mesh.visual, "material", None), "baseColorTexture", None)
    stats = {
        "triangles": len(mesh.faces),
        "texture_px": max(image.size) if image is not None else 0,
        "collision_triangles": len(collision.faces),
    }
    estimate = ScaleEstimate(
        method="survey",
        scale=unit_m,
        residual_m=None,
        notes=f"imported {source} mesh {src.name}: its own units ({unit} x {scale:g}), up = {up}, "
        f"source point {np.round(origin, 3).tolist()} is the package origin",
    )
    publish_revision(
        out_dir,
        revision=revision,
        quality="full",
        name=site,
        scale=estimate,
        gravity_residual_deg=0.0,
        frame_id=load_or_create_frame_id(work_dir, site),
        aligned_to_preview=False,
        alignment_residual_m=None,
        spawn=where,
        mesh_stats=stats,
        scale_candidates=[estimate],
    )
    size = (mesh.bounds[1] - mesh.bounds[0]).round(2).tolist()
    return {
        "site": site,
        "source": source,
        "revision": revision,
        "out": str(out_dir),
        "up": up,
        "m_per_unit": unit_m,
        "origin_source_units": origin,
        "size_m": {"x": size[0], "y": size[1], "z": size[2]},
        "interior": interior,
        "spawn": where,
        "cameras": len(cameras),
        "input": {"pieces": pieces_in, "triangles": triangles_in},
        **stats,
        "problems": validate_package(out_dir),
    }
