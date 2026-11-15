"""Turns tiles captured from a Matterport tour (web/viewer/tour.html?capture=1 writes them to world/_scans/<id>/raw)
into the room mesh the pictures use: world/_scans/<id>/tiles (one OBJ and PNG per tile, in the world's frame),
room.glb for the 3D page, and scan.json listing them. Where the tour's detail levels overlap, the finest wins.
It also measures the table tops on the mesh and writes world/scenarios/<id>.fit.json (the tour alignment and
each table's footprint), which the trace script reads. Run from the repo root: python world/scenarios/tools/stitch_scan.py jrr
The mesh is then cleaned for showing (scan_clean.py: people, chairs and loose things out, holes patched, baked light
evened); pass --as-scanned to keep it as captured.
world/_scans is not committed: the mesh is Matterport's, taken from the public tour for this demo."""
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

LOW_M, HIGH_M, MARGIN_M, CELL, RISE_M = 2.6, 6.0, 1.5, 0.04, 3.0
LEVEL_BIN, LEVEL_M2 = 0.25, 25.0  # a floor above: this much level surface within one height band of this size  # top view shows below LOW_M; the film and 3D page up to HIGH_M


def load(raw: Path) -> dict:
    tiles = {}
    for f in raw.glob("*.pos"):
        k, m = f.stem, re.match(r"L(\d+)_(\d+)_", f.stem)
        if not m or not all((raw / (k + e)).exists() for e in (".uv", ".idx", ".jpg")):
            continue
        tiles[k] = {"lod": int(m[1]), "chunk": int(m[2]), "pos": np.fromfile(f, np.float32).reshape(-1, 3),
                    "uv": np.fromfile(raw / (k + ".uv"), np.float32).reshape(-1, 2), "idx": np.fromfile(raw / (k + ".idx"), np.uint32).reshape(-1, 3).astype(np.int64)}
    return tiles


def finest(tiles: dict) -> dict:
    """Drop every triangle that reaches into the bounds of a finer tile: a corner, an edge midpoint or its middle
    inside one is enough. A coarse tile's triangles are large, so testing the middle alone leaves sheets of it
    hanging across rooms that finer tiles already cover."""
    cells = defaultdict(list)
    for t in tiles.values():
        cells[(t["lod"], t["chunk"])].append(t["pos"])
    # a tile's bounds are those of what is in it, which stops at the table tops in an open hall; the tile itself goes
    # on up, so the test reaches RISE_M above and below (the tour's frame has Y up)
    grow = np.array([0.03, RISE_M, 0.03])
    boxes = [(lod, np.concatenate(ps).min(0) - grow, np.concatenate(ps).max(0) + grow) for (lod, _), ps in cells.items()]
    weights = np.array([(1, 0, 0), (0, 1, 0), (0, 0, 1), (.5, .5, 0), (0, .5, .5), (.5, 0, .5), (1 / 3, 1 / 3, 1 / 3)])
    for t in tiles.values():
        pts = np.einsum("kc,tcd->tkd", weights, t["pos"][t["idx"]].astype(float))  # [triangles, 7 points, 3]
        drop = np.zeros(len(pts), bool)
        for lod, lo, hi in boxes:
            if lod > t["lod"]:
                drop |= np.all((pts >= lo) & (pts <= hi), 2).any(1)
        t["drop"] = drop
    # The finest level is sometimes missing a piece of floor (a tile part that never loaded). Where it is, keep the
    # next level's floor rather than leave a hole: level triangles near floor height with no finest floor under them.
    top = max(t["lod"] for t in tiles.values())

    def floor_cells(t, which):
        tri = t["pos"][t["idx"]].astype(float)[which]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        level = (np.abs(n[:, 1]) > 0.9 * (np.linalg.norm(n, axis=1) + 1e-12)) & (np.abs(tri[:, :, 1]).max(1) < 0.35)
        pts = np.einsum("kc,tcd->tkd", weights, tri)
        return level, np.floor(pts[:, :, 0] / 0.25).astype(np.int64) * 100003 + np.floor(pts[:, :, 2] / 0.25).astype(np.int64)

    have = np.unique(np.concatenate([c[lv].ravel() for t in tiles.values() if t["lod"] == top for lv, c in [floor_cells(t, ~t["drop"])]] or [np.zeros(0, np.int64)]))
    for t in tiles.values():
        if t["lod"] == top - 1 and t["drop"].any():
            level, cells = floor_cells(t, slice(None))
            t["drop"] &= ~(level & (np.isin(cells, have).mean(1) < 0.3))
    for t in tiles.values():
        t["idx"] = t["idx"][~t.pop("drop")]
    return {k: t for k, t in tiles.items() if len(t["idx"])}


def level_name(fid) -> str:
    """ "f2" -> "Floor 2"; anything else as it is."""
    m = re.match(r"f(\d+)$", fid or "")
    return f"Floor {m[1]}" if m else str(fid)


def compact(pos, uv, idx):
    used = np.unique(idx)
    remap = -np.ones(len(pos), np.int64)
    remap[used] = np.arange(len(used))
    return pos[used], uv[used], remap[idx]


def table_grid(tiles: dict, lo, hi):
    """Where there is a level surface at table height, on a grid of CELL metres: (grid, heights)."""
    shape = np.ceil((hi - lo) / CELL).astype(int) + 1
    grid, zs = np.zeros(shape, bool), np.zeros(shape, np.float32)
    for t in tiles.values():
        tri = t["w"][t["idx"]]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        ok = (np.abs(n[:, 2]) > 0.9 * np.linalg.norm(n, axis=1) + 1e-12) & (tri[:, :, 2].min(1) > 0.68) & (tri[:, :, 2].max(1) < 0.82)
        tri = tri[ok]
        if not len(tri):
            continue
        edge = np.linalg.norm(tri[:, [1, 2, 0]] - tri, axis=2).max(1)
        steps = np.clip(np.ceil(edge / (CELL * 0.7)).astype(int), 1, 80)  # sample each triangle finely enough to fill its cells
        for n in np.unique(steps):
            a, b = np.meshgrid(np.arange(n + 1), np.arange(n + 1))
            a, b = a[a + b <= n] / n, b[a + b <= n] / n
            w = np.stack([1 - a - b, a, b], 1)
            p = np.einsum("kc,tcd->tkd", w, tri[steps == n]).reshape(-1, 3)
            ij = np.floor((p[:, :2] - lo) / CELL).astype(int)
            good = np.all((ij >= 0) & (ij < shape), 1)
            grid[ij[good, 0], ij[good, 1]] = True
            zs[ij[good, 0], ij[good, 1]] = p[good, 2]
    return grid, zs


def main(wid: str, clean: bool = True) -> None:
    repo = Path(__file__).resolve().parents[3]
    scen, out = repo / "world" / "scenarios", repo / "world" / "_scans" / wid
    world = json.loads((scen / f"{wid}.json").read_text())
    M = np.array(world["tour"]["to_model"], float)
    tiles = finest(load(out / "raw"))
    if not tiles:
        sys.exit(f"no captured tiles in {out / 'raw'}: open tour.html?run=...&capture=1 first")
    top = max(t["lod"] for t in tiles.values())
    tiles = {k: t for k, t in tiles.items() if t["lod"] >= top - 1}  # what is left of the coarsest levels is a few huge triangles with smeared colour
    pts = np.array([p for r in world["rooms"] for p in r["polygon"]], float)
    lo, hi = pts.min(0) - MARGIN_M, pts.max(0) + MARGIN_M
    for t in tiles.values():
        t["w"] = (t["pos"].astype(float) - M[:, 3]) @ M[:, :3]
    tables = [o for o in world.get("obstacles", []) if "table" in o["id"]]
    grid, zs = table_grid(tiles, lo, hi)
    cell = lambda b, d: (np.floor((np.array(b["min"][:2]) + d - lo) / CELL).astype(int), np.ceil((np.array(b["max"][:2]) + d - lo) / CELL).astype(int))
    best, shift = -1, np.zeros(2)
    for dx in np.arange(-1.2, 1.2001, CELL):  # one shift for the whole trace: where do the traced tables cover the most table top
        for dy in np.arange(-1.2, 1.2001, CELL):
            s = 0
            for o in tables:
                a, b = cell(o["box"], np.array([dx, dy]))
                s += int(grid[max(a[0], 0):b[0], max(a[1], 0):b[1]].sum())
            if s > best:
                best, shift = s, np.array([dx, dy])
    print(f"the traced tables fit the scan best moved by {shift.round(2)} m; the tour alignment takes that up")
    # move the scan instead of the trace: the walls, stairs and rooms then line up too
    S = np.array([M[:, :3] @ np.array([shift[0], shift[1], 0.0])]).T
    M = np.hstack([M[:, :3], M[:, 3:] + S])
    for t in tiles.values():
        t["w"] = (t["pos"].astype(float) - M[:, 3]) @ M[:, :3]
    grid, zs = table_grid(tiles, lo, hi)
    fit = {}
    for o in tables:
        a, b = cell(o["box"], np.array([-0.3, -0.3]))[0], cell(o["box"], np.array([0.3, 0.3]))[1]
        a = np.maximum(a, 0)
        ii, jj = np.nonzero(grid[a[0]:b[0], a[1]:b[1]])
        if len(ii) < 150:
            print("  no table top found near", o["id"], "- kept as traced")
            continue
        x0, x1 = np.percentile(ii, [4, 96]) * CELL + a[0] * CELL + lo[0]
        y0, y1 = np.percentile(jj, [4, 96]) * CELL + a[1] * CELL + lo[1]
        top = float(np.median(zs[a[0]:b[0], a[1]:b[1]][ii, jj]))
        fit[o["id"]] = {"min": [round(float(x0), 2), round(float(y0), 2)], "max": [round(float(x1 + CELL), 2), round(float(y1 + CELL), 2)], "top_m": round(top, 2)}
    ids = list(fit)
    for i, a in enumerate(ids):  # neighbours end to end: split the overlap at the middle
        for b in ids[i + 1:]:
            A, B = fit[a], fit[b]
            ov = [min(A["max"][k], B["max"][k]) - max(A["min"][k], B["min"][k]) for k in (0, 1)]
            if ov[0] > 0 and ov[1] > 0:
                k = int(np.argmin(ov))
                first, second = (A, B) if A["min"][k] < B["min"][k] else (B, A)
                mid = round((first["max"][k] + second["min"][k]) / 2, 2)
                first["max"][k], second["min"][k] = mid, mid
    (scen / f"{wid}.fit.json").write_text(json.dumps({
        "note": "measured on the tour's own mesh by world/scenarios/tools/stitch_scan.py: the alignment to the tour and each table top's footprint and height",
        "to_model": [[round(float(v), 3) for v in row] for row in M], "tables": fit}, indent=1) + "\n")
    print(f"measured {len(fit)} of {len(tables)} tables -> world/scenarios/{wid}.fit.json")

    import trimesh

    import scan_clean
    px = {k: 1024 if t["lod"] >= 4 else 512 for k, t in tiles.items()}
    images = {k: np.asarray(Image.open(out / "raw" / (k + ".jpg")).convert("RGB").resize((px[k], px[k]), Image.LANCZOS)) for k in tiles}
    report = {}
    if clean:  # after measuring: the tables are fitted on the scan as it was captured
        # of the world's other obstacles, only the tall ones (a stair flight) are kept as scanned; low ones are a rail of
        # glass, which scans as splinters, or equipment standing about. The planner still avoids all of them.
        others = [(o["box"]["min"], o["box"]["max"]) for o in world.get("obstacles", []) if o["id"] not in fit and o["box"]["max"][2] >= 1.5]
        floor_h = scan_clean.floor_height(tiles, lo, hi)
        rooms = [(np.array(r["polygon"], float).min(0), np.array(r["polygon"], float).max(0)) for r in world["rooms"]]
        report, cloth = scan_clean.remove_clutter(tiles, images, fit, others, rooms, lo, hi, floor_h)
        tiles = {k: t for k, t in tiles.items() if len(t["idx"])}
        patches, more = scan_clean.relight_and_patch(tiles, images, rooms, fit, cloth, lo, hi, floor_h,
                                                             voids=[(o["box"]["min"], o["box"]["max"]) for o in world.get("obstacles", []) if "opening" in o["id"] or "stairs" in o["id"]])
        report.update(more)
        print("cleaned:", report)
    else:
        patches = []
    tdir = out / "tiles"
    tdir.mkdir(exist_ok=True)
    for old in tdir.iterdir():
        old.unlink()
    listing, scene, faces, per = [], trimesh.Scene(), 0, {}
    level_area = np.zeros(int(np.ceil((HIGH_M - LOW_M) / LEVEL_BIN)))

    def piece(name, texture, p, uv, f, img, part):
        nonlocal faces
        with open(tdir / f"{name}.obj", "w") as fh:
            fh.write("".join(f"v {a:.4f} {b:.4f} {c:.4f}\n" for a, b, c in p))
            fh.write("".join(f"vt {a:.5f} {b:.5f}\n" for a, b in uv))
            fh.write("".join(f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}\n" for a, b, c in f))
        if not (tdir / f"{texture}.png").exists():
            Image.fromarray(img).save(tdir / f"{texture}.png")
        listing.append({"mesh": f"tiles/{name}.obj", "texture": f"tiles/{texture}.png", "part": part,
                        **({"layer": "furniture"} if name.endswith("_furn") else {"layer": "bare"} if name.endswith("_bare") else {})})
        buf = io.BytesIO()
        Image.fromarray(img).save(buf, "JPEG", quality=88)
        mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.open(io.BytesIO(buf.getvalue())), metallicFactor=0.0, roughnessFactor=1.0, doubleSided=True)
        scene.add_geometry(trimesh.Trimesh(p, f, visual=trimesh.visual.TextureVisuals(uv=uv, material=mat), process=False), geom_name=name)
        faces += len(f)

    for k, t in sorted(tiles.items()):
        tri = t["w"][t["idx"]]
        c = tri.mean(1)
        keep = np.all((c[:, :2] > lo) & (c[:, :2] < hi), 1) & (tri[:, :, 2].min(1) > -0.3)
        zmax = tri[:, :, 2].max(1)
        furn = t.get("furn", np.zeros(len(tri), bool))
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        up = keep & (zmax >= LOW_M) & (zmax < HIGH_M) & (nrm[:, 2] > 0.9 * np.linalg.norm(nrm, axis=1))
        np.add.at(level_area, np.clip(((tri[up].mean(1)[:, 2] - LOW_M) / LEVEL_BIN).astype(int), 0, len(level_area) - 1), 0.5 * np.linalg.norm(nrm[up], axis=1))
        # a piece per tile, per height band (below LOW_M, above it) and per layer: the building, and the furniture in
        # it, which a viewer can hide. A piece's name ends _lo or _hi, then _furn for furniture (and _bare for the floor
        # to show in the furniture's place).
        for part, band in (("lo", keep & (zmax < LOW_M)), ("hi", keep & (zmax >= LOW_M) & (zmax < HIGH_M))):
            for layer, sel in (("", band & ~furn), ("_furn", band & furn)):
                if sel.sum() < (8 if not layer else 1):
                    continue
                p, uv, f = compact(t["w"], t["uv"], t["idx"][sel])
                piece(f"{k}_{part}{layer}", k, p, uv, f, images[k], part)
                per[t["lod"]] = per.get(t["lod"], 0) + len(f)
    for name, p, uv, f, img in patches:
        piece(f"{name}_lo" + {"patch_tables": "_furn", "patch_bare": "_bare"}.get(name, ""), name, p, uv, f, img, "lo")
    scene.export(out / "room.glb")
    # The building's levels: the world's own floors, and any floor the scan caught above them (a wide level surface
    # over LOW_M), which the world file does not describe. `partial` marks those.
    levels = [{"id": f["id"], "name": level_name(f["id"]), "z": float(f["z"])} for f in world.get("floors", [])]
    for b in np.flatnonzero(level_area >= LEVEL_M2):
        if b and level_area[b - 1] >= level_area[b] or b + 1 < len(level_area) and level_area[b + 1] > level_area[b]:
            continue  # not the peak
        z = round(LOW_M + (b + 0.5) * LEVEL_BIN, 2)
        if all(abs(z - lv["z"]) > 2.0 for lv in levels):
            nums = [int(m[1]) for lv in levels for m in [re.match(r"f(\d+)$", lv["id"] or "")] if m]
            fid = f"f{max(nums) + 1}" if nums else None
            levels.append({"id": fid, "name": level_name(fid) if fid else f"Level at {z:.1f} m", "z": z, "partial": True})
    (out / "scan.json").write_text(json.dumps({"world": wid, "frame": "the world's (metres, Z up)", "to_model": M.round(3).tolist(), "low_m": LOW_M,
                                               "levels": sorted(levels, key=lambda lv: lv["z"]), "cleaned": report or None, "tiles": listing, "glb": "room.glb"}, indent=1))
    print("levels:", [(lv["name"], lv["z"], bool(lv.get("partial"))) for lv in levels])
    print("triangles kept per detail level:", dict(sorted(per.items())))
    print(f"{len(listing)} pieces, {faces} triangles, room.glb {(out / 'room.glb').stat().st_size / 1e6:.1f} MB")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "jrr", clean="--as-scanned" not in sys.argv)
