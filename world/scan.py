"""The MatterPak's textured mesh as the pieces the pictures use, for world/matterport.py.

Writes into world/_scans/<name>/ (not committed) what world/scenarios/tools/stitch_scan.py writes for a
captured tour, so agent/tools/viz.py and web/viewer/room.html show the real room with no change:

  tiles/<texture>_lo.obj, _hi.obj   one mesh per texture, in the world's frame; `lo` is what lies below
                                    low_m (the top view shows only that, or the ceiling hides the room)
  tiles/<texture>.png               the texture, 1024 px
  room.glb                          all of it, for the 3D page
  scan.json                         the listing

The mesh is for looks only: planning uses the world's obstacles.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np

TEXTURE_PX = 1024
MARGIN_M = 1.0       # mesh further than this outside the rooms is dropped (gardens, neighbours through windows)
HIGH_M = 6.0


def read_textured_obj(path: Path) -> tuple:
    """(vertices n x 3, uv m x 2, {texture file: faces k x 3 x 2 of (vertex, uv) indices})."""
    textures, material = {}, None
    for line in path.with_suffix(".mtl").read_text().splitlines():
        part = line.split(None, 1)
        if len(part) == 2 and part[0] == "newmtl":
            material = part[1].strip()
        elif len(part) == 2 and part[0] == "map_Kd" and material:
            textures[material] = part[1].strip()
    verts, uvs, faces, current = [], [], {}, None
    with open(path, "rb") as f:
        for line in f:
            if line.startswith(b"v "):
                verts.append(line[2:].split()[:3])
            elif line.startswith(b"vt "):
                uvs.append(line[3:].split()[:2])
            elif line.startswith(b"usemtl "):
                current = faces.setdefault(textures.get(line[7:].strip().decode()), [])
            elif line.startswith(b"f ") and current is not None:
                idx = [tuple(int(x) for x in p.split(b"/")[:2]) for p in line[2:].split()]
                for k in range(1, len(idx) - 1):
                    current.append((idx[0], idx[k], idx[k + 1]))
    return (np.array(verts, float), np.array(uvs, float),
            {name: np.array(f, np.int64) - 1 for name, f in faces.items() if name and f})


def _compact(vertices, uv, faces):
    """One vertex per (position, uv) pair a face uses: (positions, uvs, triangles)."""
    pairs, inverse = np.unique(faces.reshape(-1, 2), axis=0, return_inverse=True)
    return vertices[pairs[:, 0]], uv[pairs[:, 1]], inverse.reshape(-1, 3)


def write(obj_path: str | Path, out: str | Path, world: dict, *, lift: float = 0.0) -> dict:
    """Cut the MatterPak mesh at `obj_path` into `out` for `world` (whose floor is `lift` m up in the mesh).
    Returns the listing written to scan.json."""
    import trimesh
    from PIL import Image

    obj_path, out = Path(obj_path), Path(out)
    vertices, uv, groups = read_textured_obj(obj_path)
    vertices = vertices - (0.0, 0.0, lift)
    corners = np.array([p for r in world["rooms"] for p in r["polygon"]], float)
    lo, hi = corners.min(axis=0) - MARGIN_M, corners.max(axis=0) + MARGIN_M
    low_m = round(min(2.6, min(r["ceiling_m"] for r in world["rooms"]) - 0.3), 2)   # under the lowest ceiling

    tiles = out / "tiles"
    tiles.mkdir(parents=True, exist_ok=True)
    for old in tiles.iterdir():
        old.unlink()
    listing, scene, count = [], trimesh.Scene(), 0
    for texture, faces in sorted(groups.items()):
        source = obj_path.parent / texture
        if not source.exists():
            continue
        tri = vertices[faces[:, :, 0]]
        centre, top = tri.mean(axis=1), tri[:, :, 2].max(axis=1)
        keep = np.all((centre[:, :2] > lo) & (centre[:, :2] < hi), axis=1) & (tri[:, :, 2].min(axis=1) > -0.3)
        stem = Path(texture).stem
        image = Image.open(source).convert("RGB").resize((TEXTURE_PX, TEXTURE_PX), Image.LANCZOS)
        jpeg = io.BytesIO()
        image.save(jpeg, "JPEG", quality=85)
        material = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.open(io.BytesIO(jpeg.getvalue())),
                                                       metallicFactor=0.0, roughnessFactor=1.0, doubleSided=True)
        for part, chosen in (("lo", keep & (top < low_m)), ("hi", keep & (top >= low_m) & (top < HIGH_M))):
            if chosen.sum() < 8:
                continue
            p, t, f = _compact(vertices, uv, faces[chosen])
            with open(tiles / f"{stem}_{part}.obj", "w") as fh:
                fh.write("".join(f"v {a:.4f} {b:.4f} {c:.4f}\n" for a, b, c in p))
                fh.write("".join(f"vt {a:.5f} {b:.5f}\n" for a, b in t))
                fh.write("".join(f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}\n" for a, b, c in f))
            if not (tiles / f"{stem}.png").exists():
                image.save(tiles / f"{stem}.png")
            listing.append({"mesh": f"tiles/{stem}_{part}.obj", "texture": f"tiles/{stem}.png", "part": part})
            scene.add_geometry(trimesh.Trimesh(p, f, visual=trimesh.visual.TextureVisuals(uv=t, material=material), process=False),
                               geom_name=f"{stem}_{part}")
            count += len(f)
    scene.export(out / "room.glb")
    doc = {"world": world["id"], "frame": "the world's (metres, Z up)", "to_model": world["tour"]["to_model"], "low_m": low_m,
           "tiles": listing, "glb": "room.glb", "triangles": count}
    (out / "scan.json").write_text(json.dumps(doc, indent=1))
    return doc
