"""Build a walkable exterior scene of one property from the Vexcel API (api.vexcelgroup.com/v2,
`VEXCEL_API_KEY` in the X-API-KEY header).

Vexcel serves imagery and property attributes, not a 3D mesh. What it does give is enough for a
block model at true plan scale: the ortho photo of a square around the point (about 6 cm a
pixel, with its exact bounds in the JPEG's XMP), and every structure's footprint polygon. This
drapes the ortho over the ground, extrudes each footprint into a flat-topped block and puts the
ortho on its roof. Plan dimensions (roof outline, lot, driveway, distances) are measured data.
Heights are not: the API's roof heights are used where it has plausible ones, else each block
gets `default_height_m` and is listed as assumed. Walls carry the colour of the roof edge above
them, since no wall photo is posed.

Frame of the mesh this writes: metres, x east, y north, z up, origin at the requested point on
the ground.
"""

import json
import logging
import math
import re
from pathlib import Path

import httpx
import numpy as np
import trimesh
from PIL import Image

from pipeline.matterport import secret

logger = logging.getLogger(__name__)

API = "https://api.vexcelgroup.com/v2"
LAYERS = "urban,urban-r,wide-area,urban-g"
_HEIGHT_KEYS = (
    "roof-characteristics.maximum-roof-height",
    "roof-characteristics.eave-height",
    "roof-characteristics.height",
)


def metres_per_degree(lat: float) -> tuple[float, float]:
    """(east metres per degree of longitude, north metres per degree of latitude), WGS84."""
    p = math.radians(lat)
    north = 111132.92 - 559.82 * math.cos(2 * p) + 1.175 * math.cos(4 * p)
    east = 111412.84 * math.cos(p) - 93.5 * math.cos(3 * p) + 0.118 * math.cos(5 * p)
    return east, north


def wkt_rings(wkt: str) -> list[np.ndarray]:
    """The outer ring of every polygon in a POLYGON or MULTIPOLYGON WKT, as (n, 2) lon/lat
    arrays without the closing point. Holes (courtyards) are ignored."""
    rings = []
    for polygon in re.findall(r"\(\s*\(([^()]+)\)", wkt):
        pts = np.array([[float(v) for v in pair.split()[:2]] for pair in polygon.split(",")])
        if len(pts) > 3 and np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(pts) >= 3:
            rings.append(pts)
    return rings


def geometry_rings(geometry) -> list[np.ndarray]:
    """Same, for a GeoJSON geometry dict or a WKT string."""
    if isinstance(geometry, str):
        return wkt_rings(geometry)
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    return [np.array(p[0], dtype=float)[:-1, :2] for p in polygons]


def triangulate(ring: np.ndarray) -> np.ndarray:
    """Ear-clip a simple polygon (n, 2) into (n - 2, 3) triangles of ring indices, counter
    clockwise. Good for building footprints; no holes."""
    pts = np.asarray(ring, dtype=float)
    idx = list(range(len(pts)))
    x, y = pts[:, 0], pts[:, 1]
    if 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) < 0:
        idx.reverse()

    def cross(o, a, b):
        return (pts[a, 0] - pts[o, 0]) * (pts[b, 1] - pts[o, 1]) - (pts[a, 1] - pts[o, 1]) * (
            pts[b, 0] - pts[o, 0]
        )

    triangles = []
    guard = 0
    while len(idx) > 3 and guard < 10 * len(pts) ** 2:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if cross(a, b, c) <= 1e-14:
                continue  # reflex or flat corner
            if any(
                cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0
                for p in idx
                if p not in (a, b, c)
            ):
                continue  # another vertex inside this ear
            triangles.append((a, b, c))
            idx.pop(k)
            break
        else:
            idx.pop(0)  # degenerate ring: drop a vertex rather than loop forever
    if len(idx) == 3:
        triangles.append(tuple(idx))
    return np.array(triangles, dtype=int).reshape(-1, 3)


def _number(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def structure_height(structure: dict, default_m: float) -> tuple[float, bool]:
    """(height in metres, True when it is the assumed default). The API's value is used when one
    of its height fields holds a believable number for a building (1.8 to 150 m)."""
    for key in _HEIGHT_KEYS:
        v = _number(structure.get(key))
        if v is not None and 1.8 <= v <= 150:
            return v, False
    stories = _number(structure.get("roof-characteristics.number-of-stories-below-eave"))
    if stories and 1 <= stories <= 60:
        return stories * 3.0 + 0.5, True
    return default_m, True


def block_model(
    ortho: Image.Image,
    bounds: tuple[float, float, float, float],
    lat: float,
    lon: float,
    structures: list[dict],
) -> trimesh.Trimesh:
    """Ground quad over `bounds` (west, south, east, north in degrees) plus one extruded block
    per structure (`{"ring": lon/lat array, "height": m}`), all textured from `ortho`."""
    east, north = metres_per_degree(lat)
    w, s, e, n = bounds

    def xy(lonlat):
        lonlat = np.asarray(lonlat, dtype=float)
        return np.c_[(lonlat[:, 0] - lon) * east, (lonlat[:, 1] - lat) * north]

    def uv(lonlat):
        lonlat = np.asarray(lonlat, dtype=float)
        return np.c_[(lonlat[:, 0] - w) / (e - w), (lonlat[:, 1] - s) / (n - s)]

    vertices, faces, uvs = [], [], []

    def add(points3, tris, tex):
        base = sum(len(v) for v in vertices)
        vertices.append(points3)
        faces.append(np.asarray(tris) + base)
        uvs.append(tex)

    # the ground as a grid of about 5 m cells: even triangles for collision and snapping
    cells = max(1, int(np.ceil(max((e - w) * east, (n - s) * north) / 5.0)))
    gi, gj = np.meshgrid(np.arange(cells + 1), np.arange(cells + 1), indexing="xy")
    grid = np.c_[w + (e - w) * gi.ravel() / cells, s + (n - s) * gj.ravel() / cells]
    q = (gj[:-1, :-1] * (cells + 1) + gi[:-1, :-1]).ravel()
    ground = np.concatenate(
        [np.c_[q, q + 1, q + cells + 2], np.c_[q, q + cells + 2, q + cells + 1]]
    )
    add(np.c_[xy(grid), np.zeros(len(grid))], ground, uv(grid))
    for st in structures:
        ring = st["ring"]
        k = len(ring)
        flat, tex, h = xy(ring), uv(ring), st["height"]
        tris = triangulate(flat)
        add(np.c_[flat, np.full(k, h)], tris, tex)  # roof, facing up
        # walls: each edge a quad from the ground to the roof, facing out of a CCW ring
        ccw = (
            0.5
            * np.sum(flat[:, 0] * np.roll(flat[:, 1], -1) - np.roll(flat[:, 0], -1) * flat[:, 1])
            > 0
        )
        order = np.arange(k) if ccw else np.arange(k)[::-1]
        a, b = order, np.roll(order, -1)
        quad = np.concatenate([np.c_[flat[a], np.zeros(k)], np.c_[flat[b], np.zeros(k)],
                               np.c_[flat[b], np.full(k, h)], np.c_[flat[a], np.full(k, h)]])  # fmt: skip
        i = np.arange(k)
        wall = np.concatenate([np.c_[i, i + k, i + 2 * k], np.c_[i, i + 2 * k, i + 3 * k]])
        add(quad, wall, np.concatenate([tex[a], tex[b], tex[b], tex[a]]))

    mesh = trimesh.Trimesh(np.concatenate(vertices), np.concatenate(faces), process=False)
    image = ortho.convert("RGB")
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=image, metallicFactor=0.0, roughnessFactor=1.0
    )
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.concatenate(uvs).clip(0, 1), image=image, material=material
    )
    return mesh


# ------------------------------------------------------------------------------------- the API


def _square(lat: float, lon: float, half_m: float) -> tuple[float, float, float, float]:
    east, north = metres_per_degree(lat)
    return lon - half_m / east, lat - half_m / north, lon + half_m / east, lat + half_m / north


def _bounds_wkt(b) -> str:
    w, s, e, n = b
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


def fetch(lat: float, lon: float, dest: Path, half_m: float = 35.0) -> dict:
    """Download the ortho of a square (`half_m` from centre to edge) around the point and the
    property records inside it into `dest`. Returns `{"ortho": path, "bounds": (w, s, e, n),
    "structures": [raw structure dicts], "collection": name}`."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    headers = {"X-API-KEY": secret("VEXCEL_API_KEY")}
    area = _bounds_wkt(_square(lat, lon, half_m))

    r = httpx.post(
        f"{API}/ortho/extract",
        headers=headers,
        timeout=300,
        json={"wkt": area, "srid": 4326, "layer": LAYERS, "crop": "bounding_box",
              "image-format": "jpeg"},
    )  # fmt: skip
    if r.status_code == 401:
        raise RuntimeError("Vexcel rejected the key (HTTP 401)")
    r.raise_for_status()
    (dest / "ortho.jpg").write_bytes(r.content)
    # the image is snapped to whole tiles' pixels: its true bounds are in the XMP block
    xmp = re.search(rb"<Vexcel:geometry>(.*?)</Vexcel:geometry>", r.content, re.DOTALL)
    ring = wkt_rings(xmp.group(1).decode())[0] if xmp else None
    bounds = (
        (ring[:, 0].min(), ring[:, 1].min(), ring[:, 0].max(), ring[:, 1].max())
        if ring is not None
        else _square(lat, lon, half_m)
    )
    collection = re.search(rb"<Vexcel:collection>(.*?)</Vexcel:collection>", r.content)

    structures = []
    r = httpx.get(
        f"{API}/property/extract",
        headers=headers,
        timeout=300,
        params={"wkt": area, "srid": 4326, "layer": LAYERS, "latest": "true",
                "include": "precomputed,calculated", "unit-system": "metric", "page-size": 200},
    )  # fmt: skip
    if r.status_code == 200:
        (dest / "property.json").write_text(r.text)
        for feature in r.json().get("features", []):
            structures += feature["properties"].get("structures") or []
    elif r.status_code != 404:  # 404: no property record here; the ortho still stands
        r.raise_for_status()
    return {
        "ortho": dest / "ortho.jpg",
        "bounds": bounds,
        "structures": structures,
        "collection": collection.group(1).decode() if collection else None,
    }


def build(lat: float, lon: float, work: Path, *, half_m: float = 35.0,
          default_height_m: float = 3.5) -> tuple[Path, dict]:  # fmt: skip
    """Fetch and build the block model of the square around (lat, lon). Returns the GLB path
    (metres, Z up) and a report naming every structure and where its height came from."""
    work = Path(work)
    got = fetch(lat, lon, work / "vexcel", half_m)
    w, s, e, n = got["bounds"]
    blocks, listing = [], []
    for st in got["structures"]:
        footprint = st.get("footprint.wkt")
        if not footprint:
            continue
        height, assumed = structure_height(st, default_height_m)
        for ring in geometry_rings(footprint):
            inside = (ring[:, 0] > w) & (ring[:, 0] < e) & (ring[:, 1] > s) & (ring[:, 1] < n)
            if not inside.all():
                continue  # cut by the edge of the photo
            blocks.append({"ring": ring, "height": height})
            listing.append({
                "footprint_m2": round(_number(st.get("footprint.area")) or 0.0, 1),
                "height_m": round(height, 2),
                "height_assumed": assumed,
                "roof": st.get("roof-characteristics.shape.value"),
                "roof_material": st.get("roof-characteristics.material.class"),
                "primary": str(st.get("primary-structure")).lower() == "true",
            })  # fmt: skip
    # The same building comes back once per parcel record and collection, traced slightly
    # differently each time. Keep one block per building (centres within 8 m, areas within a
    # quarter of each other), preferring a measured height over the assumed one.
    east_m, north_m = metres_per_degree(lat)
    order = sorted(range(len(blocks)), key=lambda i: (listing[i]["height_assumed"], -listing[i]["footprint_m2"]))
    kept: list[int] = []
    for i in order:
        ci = blocks[i]["ring"].mean(axis=0)
        same = False
        for j in kept:
            cj = blocks[j]["ring"].mean(axis=0)
            apart = float(np.hypot((ci[0] - cj[0]) * east_m, (ci[1] - cj[1]) * north_m))
            ratio = (listing[i]["footprint_m2"] + 1.0) / (listing[j]["footprint_m2"] + 1.0)
            if apart <= 8.0 and 0.75 <= ratio <= 1.33:
                same = True
                break
        if not same:
            kept.append(i)
    blocks = [blocks[i] for i in sorted(kept)]
    listing = [listing[i] for i in sorted(kept)]

    with Image.open(got["ortho"]) as ortho:
        mesh = block_model(ortho, got["bounds"], lat, lon, blocks)
        gsd = (e - w) * metres_per_degree(lat)[0] / ortho.width
    out = work / "vexcel.glb"
    mesh.export(out)
    report = {
        "lat": lat,
        "lon": lon,
        "collection": got["collection"],
        "ortho_m_per_px": round(gsd, 4),
        "structures": listing,
        "heights_assumed": sum(b["height_assumed"] for b in listing),
    }
    (work / "vexcel.json").write_text(json.dumps(report, indent=2))
    return out, report
