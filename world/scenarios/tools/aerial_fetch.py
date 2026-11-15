"""Fetch the Vexcel aerial photo and building footprints of a square around a point, for an outdoor scenario.

    python world/scenarios/tools/aerial_fetch.py <name> <lat> <lon> [--half 30]
    python world/scenarios/tools/aerial_fetch.py <name> --heights      # add the height of what stands on the ground

Writes world/scenarios/aerial/<name>.jpg (the ortho photo, north up) and <name>.site.json: the photo's extent
in metres around the point (x east, y north), the metres per pixel, the collection it came from, and every
structure's footprint ring in the same frame with Vexcel's roof height where it has one.
Needs VEXCEL_API_KEY in the environment or in .env. Vexcel's API: api.vexcelgroup.com/v2 (the same calls as
world/pathfinder/backend/pipeline/vexcel.py).
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
from pathlib import Path

import httpx
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "world" / "scenarios" / "aerial"
API = "https://api.vexcelgroup.com/v2"
LAYERS = "urban,urban-r,wide-area,urban-g"
HEIGHTS = ("roof-characteristics.maximum-roof-height", "roof-characteristics.eave-height", "roof-characteristics.height")


def _key() -> str:
    if os.environ.get("VEXCEL_API_KEY"):
        return os.environ["VEXCEL_API_KEY"]
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith("VEXCEL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("VEXCEL_API_KEY is not set")


def metres_per_degree(lat: float):
    p = math.radians(lat)
    return (111412.84 * math.cos(p) - 93.5 * math.cos(3 * p) + 0.118 * math.cos(5 * p),
            111132.92 - 559.82 * math.cos(2 * p) + 1.175 * math.cos(4 * p))


def rings(wkt: str) -> list:
    out = []
    for polygon in re.findall(r"\(\s*\(([^()]+)\)", wkt):
        pts = [[float(v) for v in pair.split()[:2]] for pair in polygon.split(",")]
        if len(pts) > 3 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) >= 3:
            out.append(pts)
    return out


def fetch(name: str, lat: float, lon: float, half: float) -> dict:
    east, north = metres_per_degree(lat)
    w, s, e, n = lon - half / east, lat - half / north, lon + half / east, lat + half / north
    area = f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
    headers = {"X-API-KEY": _key()}
    r = httpx.post(f"{API}/ortho/extract", headers=headers, timeout=300,
                   json={"wkt": area, "srid": 4326, "layer": LAYERS, "crop": "bounding_box", "image-format": "jpeg"})
    r.raise_for_status()
    xmp = re.search(rb"<Vexcel:geometry>(.*?)</Vexcel:geometry>", r.content, re.DOTALL)
    if xmp:  # the image is snapped to whole pixels: its true bounds are in the XMP block
        ring = rings(xmp.group(1).decode())[0]
        w, e = min(p[0] for p in ring), max(p[0] for p in ring)
        s, n = min(p[1] for p in ring), max(p[1] for p in ring)
    collection = re.search(rb"<Vexcel:collection>(.*?)</Vexcel:collection>", r.content)
    OUT.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    img.save(OUT / f"{name}.jpg", quality=88)

    def xy(p):
        return [round((p[0] - lon) * east, 2), round((p[1] - lat) * north, 2)]

    structures = []
    r = httpx.get(f"{API}/property/extract", headers=headers, timeout=300,
                  params={"wkt": area, "srid": 4326, "layer": LAYERS, "latest": "true", "include": "precomputed,calculated",
                          "unit-system": "metric", "page-size": 200})
    if r.status_code == 200:
        for feature in r.json().get("features", []):
            for st in feature["properties"].get("structures") or []:
                h = None
                for k in HEIGHTS:
                    v = st.get(k)
                    v = v.get("value") if isinstance(v, dict) else v
                    try:
                        if v is not None and 1.5 < float(v) < 400:
                            h = round(float(v), 2)
                            break
                    except (TypeError, ValueError):
                        pass
                for ring in rings(st.get("footprint.wkt") or ""):
                    structures.append({"ring": [xy(p) for p in ring], "height_m": h,
                                       "primary": str(st.get("primary-structure")).lower() == "true"})
    elif r.status_code != 404:
        r.raise_for_status()
    # the same building comes back once per parcel record: keep one per centre
    kept = []
    for st in sorted(structures, key=lambda s: s["height_m"] is None):
        c = [sum(p[i] for p in st["ring"]) / len(st["ring"]) for i in (0, 1)]
        if all(math.hypot(c[0] - k["c"][0], c[1] - k["c"][1]) > 3.0 for k in kept):
            kept.append({**st, "c": c})
    site = {"name": name, "lat": lat, "lon": lon,
            "source": f"Vexcel Imaging ortho photo and building footprints, collection {collection.group(1).decode() if collection else 'unknown'}",
            "frame": "metres, x east, y north, origin at lat/lon",
            "image": f"world/scenarios/aerial/{name}.jpg", "pixels": list(img.size),
            "extent": [round((w - lon) * east, 3), round((s - lat) * north, 3), round((e - lon) * east, 3), round((n - lat) * north, 3)],
            "m_per_px": round((e - w) * east / img.size[0], 4),
            "structures": [{k: v for k, v in st.items() if k != "c"} for st in kept]}
    (OUT / f"{name}.site.json").write_text(json.dumps(site, indent=1) + "\n")
    return site


# ------------------------------------------------------------------ the height of what stands on the ground

OBSTACLE_HINT_M = 0.15  # only for the printed summary; nav decides what blocks the robot (nav/grid.py)


def _tiff(content: bytes):
    """(float array, [west, south, east, north] in Web Mercator metres, {collection, layer, captured}) of a
    single-band GeoTIFF from Vexcel. Needs `tifffile` and `imagecodecs` (not project dependencies: the rasters
    are LERC-compressed), e.g. `uv pip install tifffile imagecodecs`."""
    import tifffile

    with tifffile.TiffFile(io.BytesIO(content)) as t:
        page = t.pages[0]
        a = page.asarray().astype("float32")
        sx, sy = page.tags["ModelPixelScaleTag"].value[:2]
        i, j, _, x, y, _ = page.tags["ModelTiepointTag"].value[:6]
        xmp = page.tags["XMP"].value if "XMP" in page.tags else b""
    xmp = xmp.decode(errors="replace") if isinstance(xmp, bytes) else xmp
    told = dict(re.findall(r"<Vexcel:([a-zA-Z-]+)>([^<]*)", xmp))
    meta = {"collection": told.get("collection"), "layer": told.get("layer"),
            "captured": [told.get("first-capture-date"), told.get("last-capture-date")]}
    west, north = x - i * sx, y + j * sy
    return a, [west, north - a.shape[0] * sy, west + a.shape[1] * sx, north], meta


def _mercator(lon: float, lat: float):
    r = 6378137.0
    return r * math.radians(lon), r * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def heights(name: str) -> dict:
    """Fetch Vexcel's surface model (DSM: the top of everything; its collection and capture dates are kept) and terrain
    model (DTM: the bare ground) for a site already fetched, and write world/scenarios/aerial/<name>.height.npz:

        height  float16, metres above the ground, one value per pixel of the photo (row 0 is the north edge)
        water   bool, pixels the photo shows as open water (a pool is flat in the surface model, so only its colour gives it away)

    Height is DSM minus DTM, shifted so that the commonest value (open ground) is zero: the two models come from
    different layers and sit a few decimetres apart."""
    import numpy as np

    site = json.loads((OUT / f"{name}.site.json").read_text())
    lat, lon = site["lat"], site["lon"]
    east, north = metres_per_degree(lat)
    x0, y0, x1, y1 = site["extent"]
    w, s, e, n = lon + x0 / east, lat + y0 / north, lon + x1 / east, lat + y1 / north
    area = f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
    headers = {"X-API-KEY": _key()}
    got = {}
    for kind, layer in (("dsm", "urban"), ("dtm", LAYERS)):
        r = httpx.post(f"{API}/{kind}/extract", headers=headers, timeout=300,
                       json={"wkt": area, "srid": 4326, "layer": layer, "crop": "bounding_box"})
        r.raise_for_status()
        got[kind] = _tiff(r.content)
    W, H = site["pixels"]
    mw, ms = _mercator(w, s)
    me, mn = _mercator(e, n)
    px = mw + (np.arange(W) + 0.5) / W * (me - mw)          # the photo's pixel centres, in the rasters' own frame
    py = mn - (np.arange(H) + 0.5) / H * (mn - ms)

    def sample(kind):
        a, (bw, bs, be, bn), _ = got[kind]
        j = np.clip(((px - bw) / (be - bw) * a.shape[1]).astype(int), 0, a.shape[1] - 1)
        i = np.clip(((bn - py) / (bn - bs) * a.shape[0]).astype(int), 0, a.shape[0] - 1)
        return a[np.ix_(i, j)]

    dsm, dtm = sample("dsm"), sample("dtm")
    known = (dsm > -9000) & (dtm > -9000)
    diff = np.where(known, dsm - dtm, np.nan)
    hist, edges = np.histogram(diff[known & (np.abs(diff) < 2)], bins=160, range=(-2, 2))
    ground = float((edges[hist.argmax()] + edges[hist.argmax() + 1]) / 2)
    height = np.where(known, diff - ground, 99.0)            # nothing known: treated as blocked
    rgb = np.asarray(Image.open(OUT / f"{name}.jpg").convert("RGB"), dtype=float)
    r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    water = (b_ > 110) & (b_ > r_ * 1.25) & (g_ > r_ * 1.1) & (height < 0.5)  # light blue-green and flat
    np.savez_compressed(OUT / f"{name}.height.npz", height=height.astype("float16"), water=water)
    site["height"] = {"file": f"world/scenarios/aerial/{name}.height.npz",
                      "source": "Vexcel Imaging surface model (DSM) minus terrain model (DTM), ground set to zero; "
                                "open water from the photo's colour",
                      "dsm": got["dsm"][2], "dtm": got["dtm"][2],
                      "dsm_m_per_px": round((got["dsm"][1][2] - got["dsm"][1][0]) / got["dsm"][0].shape[1] * (x1 - x0) / (me - mw), 4),
                      "ground_offset_m": round(ground, 3)}
    (OUT / f"{name}.site.json").write_text(json.dumps(site, indent=1) + "\n")
    return {"ground_offset_m": round(ground, 3), "standing_share": round(float((height > OBSTACLE_HINT_M).mean()), 3),
            "water_share": round(float(water.mean()), 4), "max_m": round(float(height[height < 90].max()), 1)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("lat", type=float, nargs="?")
    ap.add_argument("lon", type=float, nargs="?")
    ap.add_argument("--heights", action="store_true", help="for a site already fetched: add its height raster (<name>.height.npz)")
    ap.add_argument("--half", type=float, default=30.0)
    a = ap.parse_args()
    if a.heights:
        print(f"{a.name}: heights {heights(a.name)}")
        raise SystemExit(0)
    s = fetch(a.name, a.lat, a.lon, a.half)
    print(f"{a.name}: {s['pixels']} px, {s['m_per_px']} m/px, extent {s['extent']}, {len(s['structures'])} structures, {s['source']}")
