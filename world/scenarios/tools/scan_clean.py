"""Cleans a stitched room scan for showing: takes out what stands about on the floor (people, chairs, bags, boxes,
things left on tables), drops loose shards, patches the holes that leaves, and evens out the light and shade
the scanner's photos baked into the textures. Used by stitch_scan.py after it has measured the tables.

The rule throughout is to keep the scan wherever it is good and repair only what is not, because the scan's own
surfaces (a draped cloth, floorboards) look real and anything drawn in their place does not:

- Kept by where it is: the floor, anything in a column with scan all the way up (walls, pillars), tall obstacles
  (stairs), everything above head height.
- Kept by what it is: in a table's volume, the triangles whose texture is the cloth's colour. A chair pushed
  against a cloth or a laptop on it is not that colour.
- A table too deep in shade to brighten without noise, or with little of its cloth left, is replaced by a copy
  of the best scanned table: they are all the same table under the same cloth.
- The floor's light is divided out up to a limit; past it (deep shade, tinted sun, gaps) the boards are copied
  from a well-lit stretch further along the same boards.

The plan's obstacles are not changed by this: a chair removed here was never an obstacle to the planner."""
import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

CELL = 0.10            # grid for "is there a wall in this column", metres
WALL_BAND = (1.9, 2.4)  # a column with scan in this height band, and most of the way up to it, is structure
WALL_BINS = 7
FINE = 0.025           # grid for "is this under the wall above it"
UPPER = (1.5, 2.4)     # the part of a wall that nothing leans on
FLOOR_TOP = 0.07       # below this a triangle is floor
HEAD = 1.95            # at or above this nothing is clutter
TOP_BAND = 0.06        # a cloth lies within this of the measured table top (it wrinkles)
CLOTH_M = 0.60         # and hangs no further than this below it
EDGE_M = 0.30          # nothing is cleared within this of a room's outline: a bench or a rail on the line would be cut in two
SHARD_M2 = 0.30        # a loose piece smaller than this is dropped
FLOOR_CELL = 0.01      # the floor picture: fine enough to show boards, since repairs are painted from it
LIGHT_CELL = 0.12      # the grid the light is read on
UNDER = 20             # the floor underlay is made of squares this many floor cells a side
HOLE_M2 = 3.0          # a gap in the floor up to this size is closed; larger ones are shafts and voids
EXPOSURE = 1.10
FLOOR_GAIN = (0.7, 3.2)  # how far a floor texel may be darkened or brightened; past that it is repaired
CLOTH_GAIN = (0.8, 2.0)  # one brightness factor per table; a table needing more is replaced
CLOTH_GOAL = 90          # the tables are brought to the brightness of the best-lit ones: this percentile of them
LUMA = np.array([0.299, 0.587, 0.114])


def samples(tri, step, cap=300):
    """Points covering each triangle no more than `step` apart: yields (triangle indices, weights [points, 3])."""
    edge = np.linalg.norm(tri[:, [1, 2, 0]] - tri, axis=2).max(1)
    n = np.clip(np.ceil(edge / step).astype(int), 1, cap)
    for k in np.unique(n):
        sel = np.flatnonzero(n == k)
        a, b = np.meshgrid(np.arange(k + 1), np.arange(k + 1))
        m = a + b <= k
        w = np.stack([1 - (a[m] + b[m]) / k, a[m] / k, b[m] / k], 1)
        for part in np.array_split(sel, len(sel) * len(w) // 1_500_000 + 1):
            if len(part):
                yield part, w


def _cells(xy, lo, shape, cell):
    ij = np.floor((xy - lo) / cell).astype(int)
    return np.clip(ij, 0, np.array(shape) - 1)


def floor_height(tiles: dict, lo, hi):
    """The floor's height on a CELL grid. A scan this size drifts by several centimetres from one end of a hall to
    the other, so "is this the floor" has to be asked against the floor nearby, not against zero."""
    shape = tuple(np.ceil((hi - lo) / CELL).astype(int) + 1)
    low = np.full(shape, np.inf)
    for t in tiles.values():
        tri = t["w"][t["idx"]]
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        tri = tri[(np.abs(nrm[:, 2]) > 0.9 * (np.linalg.norm(nrm, axis=1) + 1e-12)) & (tri[:, :, 2].max(1) < 0.35) & (tri[:, :, 2].min(1) > -0.35)]
        for part, w in samples(tri, CELL * 0.7):
            p = np.einsum("pc,tcd->tpd", w, tri[part]).reshape(-1, 3)
            ij = _cells(p[:, :2], lo, shape, CELL)
            np.minimum.at(low, (ij[:, 0], ij[:, 1]), p[:, 2])
    seen = np.isfinite(low)
    h = ndimage.median_filter(_fill(np.where(seen, low, 0.0), seen), size=15)  # 1.5 m: wider than a stair tread or a low box
    return ndimage.gaussian_filter(h, 2.0)


def _above(h, pos, lo):
    """Height of each point above the floor under it."""
    return pos[:, 2] - ndimage.map_coordinates(h, [(pos[:, 0] - lo[0]) / CELL - 0.5, (pos[:, 1] - lo[1]) / CELL - 0.5], order=1, mode="nearest")


def tri_colour(t, img):
    """Mean texture colour of each triangle, from four points inside it."""
    H, W = img.shape[:2]
    w = np.array([[1 / 3, 1 / 3, 1 / 3], [.6, .2, .2], [.2, .6, .2], [.2, .2, .6]])
    uv = np.einsum("kc,tcd->tkd", w, t["uv"][t["idx"]].astype(float))
    px = np.clip((uv[..., 0] * W).astype(int), 0, W - 1)
    py = np.clip(((1 - uv[..., 1]) * H).astype(int), 0, H - 1)
    return img[py, px].astype(float).mean(1)


def is_cloth(rgb):
    """The tablecloths' orange, by the share of red and blue, so it holds in shade as in sun."""
    s = rgb.sum(1) + 1e-6
    return (s > 30) & (rgb[:, 0] / s > 0.50) & (rgb[:, 2] / s < 0.16)


def _table_parts(c, zmax, f, cloth):
    """(top, sides) of a table's cloth among triangles with centres `c`."""
    mn, mx = np.array(f["min"]), np.array(f["max"])
    within = lambda pad: np.all((c[:, :2] >= mn - pad) & (c[:, :2] <= mx + pad), 1)
    top = within(0.10) & (zmax <= f["top_m"] + TOP_BAND) & (c[:, 2] >= f["top_m"] - TOP_BAND) & cloth
    side = within(0.16) & ~within(-0.12) & (c[:, 2] < f["top_m"] - TOP_BAND) & (c[:, 2] > f["top_m"] - CLOTH_M) & cloth
    return top, side


def _area(tri):
    return 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)


def remove_clutter(tiles: dict, images: dict, tables: dict, keep_boxes: list, rooms: list, lo, hi, h) -> tuple[dict, dict]:
    """Drop the triangles of things standing about and replace tables too dark or too torn to show.
    `tables` is {id: {"min", "max", "top_m"}}; `keep_boxes` are other obstacles' boxes [(min xyz, max xyz)], kept
    whole. `rooms` are [(min xy, max xy)]: only inside them is anything cleared. Past a room's walls the scan is
    left exactly as captured (someone on a bench in a wall niche stays, whole), because cutting a thing out of a
    wall leaves a hole in its shape and nothing behind it. Adds tiles (and their pictures) for replaced tables. Returns (counts for the report,
    {table id: its cloth's colour as scanned})."""
    shape = tuple(np.ceil((hi - lo) / CELL).astype(int) + 1)
    # A wall or pillar has scan all the way up its column. Under a stair flight or a balcony there is scan overhead
    # too, but nothing between it and the chair below, so the column is split into WALL_BINS heights from knee to
    # head and most of them have to be filled.
    edges = np.linspace(0.3, WALL_BAND[1], WALL_BINS + 1)
    filled = np.zeros((*shape, WALL_BINS), bool)
    for t in tiles.values():
        tri = t["w"][t["idx"]]
        tri = tri[(tri[:, :, 2].max(1) > edges[0]) & (tri[:, :, 2].min(1) < edges[-1])]
        for part, w in samples(tri, CELL * 0.7):
            p = np.einsum("pc,tcd->tpd", w, tri[part]).reshape(-1, 3)
            p = p[(p[:, 2] > edges[0]) & (p[:, 2] < edges[-1])]
            ij = _cells(p[:, :2], lo, shape, CELL)
            filled[ij[:, 0], ij[:, 1], np.clip(np.searchsorted(edges, p[:, 2]) - 1, 0, WALL_BINS - 1)] = True
    wall = filled[..., edges[:-1] >= WALL_BAND[0] - 1e-9].any(-1) & (filled.sum(-1) >= WALL_BINS * 0.7)
    wall = ndimage.binary_dilation(wall, iterations=1)
    # Within such a column, only what stands under the wall itself: a wall or pillar goes straight up, so its lower
    # part lies under its upper part, and someone sitting against it, or a bench along it, does not. `upper` is
    # where there is scan between chest and head height, on a fine grid, with a few centimetres' allowance.
    fshape = tuple(np.ceil((hi - lo) / FINE).astype(int) + 1)
    upper = np.zeros(fshape, bool)
    for t in tiles.values():
        tri = t["w"][t["idx"]]
        tri = tri[(tri[:, :, 2].max(1) > UPPER[0]) & (tri[:, :, 2].min(1) < UPPER[1])]
        for part, w in samples(tri, FINE * 0.7):
            p = np.einsum("pc,tcd->tpd", w, tri[part]).reshape(-1, 3)
            p = p[(p[:, 2] > UPPER[0]) & (p[:, 2] < UPPER[1])]
            ij = _cells(p[:, :2], lo, fshape, FINE)
            upper[ij[:, 0], ij[:, 1]] = True
    upper = ndimage.binary_dilation(upper, iterations=3)
    four = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1 / 3, 1 / 3, 1 / 3]])

    before = 0
    stat = {tid: {"top": 0.0, "side": 0.0, "rgb": [], "wt": []} for tid in tables}
    for k, t in tiles.items():
        tri = t["w"][t["idx"]]
        c, zmax = tri.mean(1), tri[:, :, 2].max(1)
        ij = _cells(c[:, :2], lo, shape, CELL)
        floor = zmax - (c[:, 2] - _above(h, c, lo)) < FLOOR_TOP
        fij = _cells(np.einsum("kc,tcd->tkd", four, tri[:, :, :2]).reshape(-1, 2), lo, fshape, FINE)
        under = upper[fij[:, 0], fij[:, 1]].reshape(-1, 4).mean(1) >= 0.5
        indoors = np.zeros(len(c), bool)
        for rl, rh in rooms:
            indoors |= np.all((c[:, :2] > np.array(rl) + EDGE_M) & (c[:, :2] < np.array(rh) - EDGE_M), 1)
        keep = ~indoors | floor | (zmax >= HEAD) | (wall[ij[:, 0], ij[:, 1]] & under)
        for bl, bh in keep_boxes:  # kept, but not spared the shard test below: a stair is one piece, a broken glass rail is splinters
            keep |= np.all((c >= np.array(bl) - [0, 0, 0.1]) & (c <= np.array(bh) + [0, 0, 0.3]), 1)
        colour, area = tri_colour(t, images[k]), _area(tri)
        cloth = is_cloth(colour)
        t["floor"], t["base"], t["parts"] = floor, keep, {}
        for tid, f in tables.items():
            top, side = _table_parts(c, zmax, f, cloth)
            if top.any() or side.any():
                t["parts"][tid] = (top, side)
                stat[tid]["top"] += area[top].sum()
                stat[tid]["side"] += area[side].sum()
                stat[tid]["rgb"].append(colour[top])
                stat[tid]["wt"].append(area[top])
        before += len(tri)

    # how much of each cloth the scan has, and how bright it is
    cloth_rgb, cover = {}, {}
    for tid, f in tables.items():
        dx, dy = f["max"][0] - f["min"][0], f["max"][1] - f["min"][1]
        rgb = np.concatenate(stat[tid]["rgb"]) if stat[tid]["rgb"] else np.zeros((0, 3))
        cloth_rgb[tid] = np.median(rgb, 0) if len(rgb) > 20 else np.array([1.0, 0.5, 0.1])
        cover[tid] = (stat[tid]["top"] / (dx * dy), stat[tid]["side"] / (2 * (dx + dy) * 0.40), dx >= dy)
    lum = {tid: float(cloth_rgb[tid] @ LUMA) for tid in tables}
    goal = float(np.percentile(list(lum.values()), CLOTH_GOAL)) if lum else 100.0
    poor = {tid for tid in tables if goal / max(lum[tid], 1.0) > CLOTH_GAIN[1] or cover[tid][0] < 0.5 or cover[tid][1] < 0.35}
    # copies come from the few tables whose tops are whole (nothing was cut out of them) and well lit
    good = sorted((tid for tid in tables if tid not in poor and 0.75 < lum[tid] / goal < 1.35), key=lambda tid: -cover[tid][0])[:3]
    swapped = {tid: good[i % len(good)] for i, tid in enumerate(sorted(poor))} if good else {}  # taken in turn, so neighbours are not twins

    added = {}
    for tid, donor in swapped.items():
        fr, fd = tables[tid], tables[donor]
        cr, cd = (np.array(fr["min"]) + fr["max"]) / 2, (np.array(fd["min"]) + fd["max"]) / 2
        turn = cover[tid][2] != cover[donor][2]
        sd = (np.array(fd["max"]) - fd["min"])[::-1] if turn else np.array(fd["max"]) - fd["min"]
        scale = (np.array(fr["max"]) - fr["min"]) / sd
        for k, t in tiles.items():
            if donor not in t["parts"]:
                continue
            top, side = t["parts"][donor]
            q = t["w"][:, :2] - cd
            if turn:
                q = np.stack([-q[:, 1], q[:, 0]], 1)  # a quarter turn, so the long side lies the other way
            w = np.column_stack([cr + q * scale, t["w"][:, 2] + fr["top_m"] - fd["top_m"]])
            n = int((top | side).sum())
            added[f"{k}@{tid}"] = {"lod": t["lod"], "w": w, "uv": t["uv"], "idx": t["idx"][top | side], "floor": np.zeros(n, bool), "base": np.ones(n, bool),
                                   "parts": {}, "safe": top[top | side]}
            images[f"{k}@{tid}"] = images[k]
        cloth_rgb[tid] = cloth_rgb[donor]

    after = 0
    for k, t in tiles.items():
        keep, safe = t["base"].copy(), np.zeros(len(t["idx"]), bool)
        for tid, (top, side) in t["parts"].items():
            if tid not in swapped:  # a replaced table's own cloth goes
                keep |= top | side
                safe |= top
        t["safe"] = (safe | t["floor"])[keep]
        t["idx"] = t["idx"][keep]
        after += int(keep.sum())
    tiles.update(added)
    for t in tiles.values():
        for key in ("floor", "base", "parts"):
            t.pop(key, None)
    # loose shards: join the tiles' corners where they coincide, then drop every small piece that is not floor or a table top
    allv = np.concatenate([t["w"] for t in tiles.values()])
    _, ids = np.unique(np.round(allv * 500).astype(np.int64), axis=0, return_inverse=True)
    ids = ids.ravel()
    off, faces = 0, []
    for t in tiles.values():
        faces.append(ids[t["idx"] + off])
        off += len(t["w"])
    faces = np.concatenate(faces)
    n = int(ids.max()) + 1
    graph = coo_matrix((np.ones(len(faces) * 2, bool), (np.r_[faces[:, 0], faces[:, 1]], np.r_[faces[:, 1], faces[:, 2]])), shape=(n, n))
    _, label = connected_components(graph, directed=False)
    comp = label[faces[:, 0]]
    area = _area(np.concatenate([t["w"][t["idx"]] for t in tiles.values()]))
    small = (np.bincount(comp, weights=area)[comp] < SHARD_M2) & ~np.concatenate([t["safe"] for t in tiles.values()])
    at = 0
    for t in tiles.values():
        m = len(t["idx"])
        t["idx"] = t["idx"][~small[at:at + m]]
        t.pop("safe")
        at += m
    report = {"triangles": before, "after_clutter": after, "after_shards": int((~small).sum()), "wall_cells": int(wall.sum()),
              "cloth_scanned": {tid.split("_")[-1]: [round(float(cover[tid][0]), 2), round(float(cover[tid][1]), 2), int(lum[tid])] for tid in tables},
              "tables_replaced": {a.split("_")[-1]: b.split("_")[-1] for a, b in swapped.items()}}
    return report, cloth_rgb


def _texels(t, W, H):
    """For every triangle, points that cover its texels: yields (px, py, world positions [n, 3], triangle index [n])."""
    uv = t["uv"][t["idx"]].astype(float) * [W, H]
    tri = t["w"][t["idx"]]
    for part, w in samples(uv, 1.0, cap=400):
        p = np.einsum("pc,tcd->tpd", w, uv[part]).reshape(-1, 2)
        pos = np.einsum("pc,tcd->tpd", w, tri[part]).reshape(-1, 3)
        px = np.clip(np.floor(p[:, 0]).astype(int), 0, W - 1)
        py = np.clip(np.floor(H - p[:, 1]).astype(int), 0, H - 1)  # the picture's first row is v = 1
        yield px, py, pos, np.repeat(part, len(w))


def _fill(a, valid):
    """`a` with every cell outside `valid` given the value of the nearest cell inside it."""
    if valid.all() or not valid.any():
        return a
    i = ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    return a[tuple(i)]


def _flatten(img, valid, goal, sigma, limit):
    """Per-channel gain that brings a one-material surface (picture `img` [X, Y, 3] over cells `valid`) to the colour
    `goal`: goal over the local mean, with brightness held to `limit` and the colour shift to a narrower range.
    Returns (gain, the local brightness, how far the light's colour is from the goal's)."""
    local = np.stack([ndimage.gaussian_filter(_fill(ndimage.median_filter(img[..., c], 3), valid), sigma) for c in range(3)], -1)
    raw = goal / np.maximum(local, 1.0)
    light = (goal @ LUMA) / np.maximum(local @ LUMA, 1.0)
    cast = np.abs(raw / light[..., None] - 1).max(-1)
    return (np.clip(light, *limit)[..., None] * np.clip(raw / light[..., None], 0.6, 1.6)).astype(np.float32), (local @ LUMA).astype(np.float32), cast.astype(np.float32)


def relight_and_patch(tiles: dict, images: dict, rooms: list, tables: dict, cloth_rgb: dict, lo, hi, h, voids=()) -> tuple[list, dict]:
    """Evens the baked light in `images` ({tile: uint8 array [H, W, 3]}, changed in place) and returns the patch
    pieces [(name, vertices, uv, faces, image)]: the floor's underlay, and a plain sheet inside each table.
    `rooms` are [(min xy, max xy)] in the world's frame: inside one, the floor is brought to one colour.
    `cloth_rgb` is each table's cloth colour as scanned. `voids` are boxes [(min, max)] where the floor really is
    open (a stairwell), so a gap there is left.

    Floor: one material per room, so the local mean colour is the light and dividing it out leaves the boards.
    Cloth: one brightness factor per table, nothing local, because a cloth's folds are its shading.
    Everything else (walls, pillars, stairs): a gentler, brightness-only correction taken from the floor near it."""
    shape = tuple(np.ceil((hi - lo) / FLOOR_CELL).astype(int) + 1)
    rgb, cnt = np.zeros((shape[0] * shape[1], 3), np.float32), np.zeros(shape[0] * shape[1], np.float32)
    fx = (lo[0] + (np.arange(shape[0]) + 0.5) * FLOOR_CELL)[:, None]
    fy = (lo[1] + (np.arange(shape[1]) + 0.5) * FLOOR_CELL)[None, :]
    tids = list(tables)
    foot = np.zeros(shape, bool)        # under a table
    zone = np.full(shape, -1)           # which table's cloth could be here
    for i, tid in enumerate(tids):
        f = tables[tid]
        foot |= (fx > f["min"][0]) & (fx < f["max"][0]) & (fy > f["min"][1]) & (fy < f["max"][1])
        zone[(fx > f["min"][0] - 0.2) & (fx < f["max"][0] + 0.2) & (fy > f["min"][1] - 0.2) & (fy < f["max"][1] + 0.2)] = i
    tops = np.array([tables[t]["top_m"] for t in tids] + [1e9])

    def level_of(t):
        tri = t["w"][t["idx"]]
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        return np.abs(nrm[:, 2]) > 0.9 * (np.linalg.norm(nrm, axis=1) + 1e-12)

    for k, t in tiles.items():
        img, up = images[k], level_of(t)
        for px, py, pos, ti in _texels(t, *img.shape[1::-1]):
            fl = up[ti] & (np.abs(_above(h, pos, lo)) < FLOOR_TOP)
            if fl.any():
                ij = _cells(pos[fl, :2], lo, shape, FLOOR_CELL)
                flat, col = ij[:, 0] * shape[1] + ij[:, 1], img[py[fl], px[fl]].astype(np.float32)
                a, b = int(flat.min()), int(flat.max()) + 1  # a chunk is local, so count only its stretch of the grid
                for ch in range(3):
                    rgb[a:b, ch] += np.bincount(flat - a, weights=col[:, ch], minlength=b - a)
                cnt[a:b] += np.bincount(flat - a, minlength=b - a)
    seen = (cnt > 0).reshape(shape)
    floor = (rgb / np.maximum(cnt, 1)[:, None]).reshape(*shape, 3)
    del rgb, cnt

    # what colour each stretch of floor should be: one colour per room, and outside the rooms the brighter end of
    # what is around (on a coarser grid; the floor there may be another material). Read off the open floor only.
    table_dist = ndimage.distance_transform_edt(~foot) * FLOOR_CELL  # metres to the nearest table's footprint
    open_ = seen & (table_dist > 0.3)
    b = round(LIGHT_CELL / FLOOR_CELL)
    cs = (shape[0] // b, shape[1] // b)
    block = lambda a: a[:cs[0] * b, :cs[1] * b].reshape(cs[0], b, cs[1], b, *a.shape[2:]).sum((1, 3))
    n = block(open_.astype(np.float32))
    okc = n >= b * b // 2
    mean = block(floor * open_[..., None]) / np.maximum(n, 1)[..., None]
    cx, cy = np.meshgrid(lo[0] + (np.arange(cs[0]) + 0.5) * LIGHT_CELL, lo[1] + (np.arange(cs[1]) + 0.5) * LIGHT_CELL, indexing="ij")
    wide = np.stack([ndimage.gaussian_filter(_fill(mean[..., c], okc), 8.0) for c in range(3)], -1)
    goal = np.stack([ndimage.percentile_filter(wide[..., c], 70, size=65) for c in range(3)], -1)
    room_goals = []
    for rl, rh in rooms:
        inside = (cx > rl[0]) & (cx < rh[0]) & (cy > rl[1]) & (cy < rh[1])
        if (inside & okc).sum() > 50:
            # the room's floor colour: as bright as its well-lit floor, with the colour of its middling floor. The
            # brightest stretches are under skylights and washed pale; taking the colour from them greys the boards.
            cells = mean[inside & okc]
            lum = cells @ LUMA
            tint = np.median(cells[(lum > np.percentile(lum, 35)) & (lum < np.percentile(lum, 65))], 0)
            goal[inside] = tint * np.percentile(lum, 75) / max(tint @ LUMA, 1.0)
            room_goals.append([int(v) for v in goal[inside][0]])
    goal = np.stack([ndimage.gaussian_filter(goal[..., c], 3.0) for c in range(3)], -1)
    broad = np.sqrt(np.clip((goal @ LUMA) / np.maximum(wide @ LUMA, 1.0), 0.7, 6.0)) * EXPOSURE
    broad[ndimage.distance_transform_edt(~okc) * LIGHT_CELL > 2.0] = EXPOSURE
    broad = ndimage.gaussian_filter(broad, 2.0)
    goal_fine = np.stack([ndimage.zoom(goal[..., c], (shape[0] / cs[0], shape[1] / cs[1]), order=1) for c in range(3)], -1)[:shape[0], :shape[1]].astype(np.float32)
    fine, floor_light, cast = _flatten(floor, seen, goal_fine, 0.12 / FLOOR_CELL, FLOOR_GAIN)
    fine *= EXPOSURE
    lit = np.clip(floor * fine, 0, 255)

    # Where the light cannot simply be divided out (shade deeper than the limit, sun tinted by the cloths, the shade
    # under a table, a gap) the boards are copied from further along the same boards, where the floor is good.
    # `mend` is how far to go over to the copy: from none to all as the brightening needed passes the limit, or the
    # colour cast goes from 45% to 75% (a milder cast is taken out by the division; this is for things lying on the
    # floor and the worst of the tinted sun).
    need = (goal_fine @ LUMA) / np.maximum(floor_light, 1.0)
    mend = np.maximum(np.clip((need - 0.7 * FLOOR_GAIN[1]) / (0.4 * FLOOR_GAIN[1]), 0, 1), np.clip((cast - 0.45) / 0.3, 0, 1))
    # and small dark marks: what is left on the floor's picture of a chair's feet, a bag, a cable. A board's seam is
    # darker than its board too, but not by this much.
    spot = ndimage.binary_dilation((floor @ LUMA) < 0.62 * floor_light, iterations=3) & seen
    mend = np.maximum(mend, spot)
    mend = np.where(seen, ndimage.gaussian_filter(np.where(seen, mend, 1.0), 0.03 / FLOOR_CELL), 1.0).astype(np.float32)
    sound = seen & (mend < 0.1) & (need < 1.7) & (cast < 0.3) & (table_dist > 0.3) & ~ndimage.binary_dilation(spot, iterations=4)
    # boards run along the axis the floor changes least on, a board's width away (smoothed first: texel noise has no axis)
    lum = ndimage.uniform_filter(lit @ LUMA, 3)
    lag = int(round(0.10 / FLOOR_CELL))
    change = [np.abs(lum[lag:, :] - lum[:-lag, :])[sound[lag:, :] & sound[:-lag, :]].mean(), np.abs(lum[:, lag:] - lum[:, :-lag])[sound[:, lag:] & sound[:, :-lag]].mean()]
    along = int(np.argmin(change))
    copy, have = lit.copy(), sound.copy()
    where = np.full(shape, -1, np.int8)  # which room a cell is in: a copy must come from the same room's floor
    for i, (rl, rh) in enumerate(rooms):
        where[(fx > rl[0]) & (fx < rh[0]) & (fy > rl[1]) & (fy < rh[1])] = i
    # first along the boards, where a copy lines up with its neighbours; then across them, for a stretch that is bad
    # from one end of the hall to the other
    for axis in (along, 1 - along):
        for metres in (3.0, -3.0, 4.5, -4.5, 6.0, -6.0, 7.5, -7.5, 9.0, -9.0, 2.0, -2.0, 11.0, -11.0):
            k = int(round(metres / FLOOR_CELL))
            src, ok = np.roll(lit, k, axis=axis), np.roll(sound, k, axis=axis)
            edge = [slice(None)] * 2
            edge[axis] = slice(0, k) if k > 0 else slice(k, None)
            ok[tuple(edge)] = False  # what rolled round the end is not a neighbour
            take = ok & ~have & (np.roll(where, k, axis=axis) == where)
            copy[take], have[take] = src[take], True
    # no board to copy from: the room's floor colour with whatever grain the texel still has
    grain = np.clip((floor @ LUMA) / np.maximum(floor_light, 1.0), 0.6, 1.4)[..., None] * goal_fine * EXPOSURE
    copy[~have] = np.where(seen[..., None], grain, goal_fine * EXPOSURE)[~have]
    # a soft shadow where each table meets the floor: the scan's own was uneven and went with the light
    shade = (1 - 0.42 * np.exp(-table_dist / 0.16)).astype(np.float32)
    picture = np.clip((lit * (1 - mend[..., None]) + copy * mend[..., None]) * shade[..., None], 0, 255).astype(np.uint8)

    lum_goal = float(np.percentile([c @ LUMA for c in cloth_rgb.values()], CLOTH_GOAL)) if cloth_rgb else 100.0
    knee, toe = lum_goal * EXPOSURE * 1.2, lum_goal * EXPOSURE * 0.6
    cloth_gain = np.array([float(np.clip(lum_goal / max(cloth_rgb[t] @ LUMA, 1.0), *CLOTH_GAIN)) * EXPOSURE for t in tids] + [EXPOSURE])

    def gain_at(pos, level):
        """For points with their triangles' levelness: (gain [n, 3], how far to go over to `tone`, tone [n, 3])."""
        ij = _cells(pos[:, :2], lo, shape, FLOOR_CELL)
        up = _above(h, pos, lo)
        fl = np.abs(up) < FLOOR_TOP  # level or not: the scan crumples the floor where a chair's feet stood
        g = ndimage.map_coordinates(broad, [(pos[:, 0] - lo[0]) / LIGHT_CELL - 0.5, (pos[:, 1] - lo[1]) / LIGHT_CELL - 0.5], order=1, mode="nearest")
        g = 1 + (g - 1) * np.clip((4.0 - up) / 1.5, 0, 1)  # full strength up to 2.5 m, none above 4 m
        who = zone[ij[:, 0], ij[:, 1]]
        cloth = (who >= 0) & (pos[:, 2] < tops[who] + 0.1) & (pos[:, 2] > tops[who] - CLOTH_M - 0.05) & ~fl
        g[cloth] = cloth_gain[who[cloth]]
        g = np.repeat(g[:, None], 3, 1)
        mix, tone = np.zeros(len(pos), np.float32), np.zeros((len(pos), 3), np.float32)
        i, j = ij[fl, 0], ij[fl, 1]
        g[fl] = fine[i, j] * shade[i, j, None]
        mix[fl], tone[fl] = mend[i, j], copy[i, j] * shade[i, j, None]
        return g, mix, tone, cloth

    for k, t in tiles.items():
        img, up = images[k], level_of(t)
        H, W = img.shape[:2]
        g, mix, tone, cl = np.full((H, W, 3), np.nan, np.float32), np.zeros((H, W), np.float32), np.zeros((H, W, 3), np.float32), np.zeros((H, W), bool)
        for px, py, pos, ti in _texels(t, W, H):
            g[py, px], mix[py, px], tone[py, px], cl[py, px] = gain_at(pos, up[ti])
        done = ~np.isnan(g[..., 0])
        if done.any() and not done.all():  # carry all of it into the gaps between charts, or seams go dark
            i = tuple(ndimage.distance_transform_edt(~done, return_distances=False, return_indices=True))
            g, mix, tone, cl = g[i], mix[i], tone[i], cl[i]
        plain = img.astype(np.float32) * np.nan_to_num(g, nan=1.0)
        if cl.any():  # a patch of sun on a cloth: brightened with the rest it burns out to yellow, so the top of the range is squeezed, keeping the hue
            light = plain[cl] @ LUMA.astype(np.float32)
            over = np.maximum(light - knee, 0)
            under = np.maximum(toe - light, 0)  # and the shade a box or a laptop left on the cloth is lifted most of the way
            plain[cl] *= np.minimum((light - over + over * 0.35 + under * 0.75) / np.maximum(light, 1.0), 5.0)[:, None]
        images[k] = np.clip(plain * (1 - mix[..., None]) + tone * mix[..., None], 0, 255).astype(np.uint8)

    # The floor's underlay: the finished floor picture, laid just under all of the floor and across its smaller
    # gaps. The tiles do not meet exactly, and the cracks between them are thinner than a cell. In blocks of UNDER
    # cells, so it stays a few thousand squares.
    lab, count = ndimage.label(~seen)
    area = ndimage.sum(np.ones(shape, np.float32), lab, index=np.arange(1, count + 1)) * FLOOR_CELL ** 2
    ok = np.zeros(count + 1, bool)
    ok[1:] = area < HOLE_M2
    ok[np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])] = False
    # inside a room the floor goes wall to wall, so there every gap is closed (where equipment stood, say), except
    # under the walls themselves (the gaps a few cells wide) and where the floor is really open
    indoors = (where >= 0) & ~seen & ndimage.binary_opening(~seen, iterations=int(0.25 / FLOOR_CELL))
    for vl, vh in voids:
        indoors &= ~((fx > vl[0]) & (fx < vh[0]) & (fy > vl[1]) & (fy < vh[1]))
    want = seen | ok[lab] | indoors
    bs = (shape[0] // UNDER, shape[1] // UNDER)
    ii, jj = np.nonzero(want[:bs[0] * UNDER, :bs[1] * UNDER].reshape(bs[0], UNDER, bs[1], UNDER).any((1, 3)))
    side_m = UNDER * FLOOR_CELL
    x0, y0 = lo[0] + ii * side_m, lo[1] + jj * side_m
    z = -_above(h, np.stack([x0 + side_m / 2, y0 + side_m / 2, np.zeros(len(ii))], 1), lo) - 0.015
    quads = np.stack([np.stack([x0, y0, z], 1), np.stack([x0 + side_m, y0, z], 1), np.stack([x0 + side_m, y0 + side_m, z], 1), np.stack([x0, y0 + side_m, z], 1)], 1)
    # picture rows run along Y (north up), columns along X: uv = (x, y) over the grid
    uvq = np.stack([(quads[..., 0] - lo[0]) / (shape[0] * FLOOR_CELL), (quads[..., 1] - lo[1]) / (shape[1] * FLOOR_CELL)], -1)
    base = np.arange(len(ii))[:, None] * 4
    faces = np.concatenate([base + [0, 1, 2], base + [0, 2, 3]])
    pieces = [("patch_floor", quads.reshape(-1, 3), uvq.reshape(-1, 2), faces, np.ascontiguousarray(picture.transpose(1, 0, 2)[::-1]))]

    # Inside each table, a plain sheet in that table's own cloth colour: a top just under the scanned one and sides
    # just inside it, seen only through the gaps where a chair or a laptop was cut away. Thin legs, as the scanned
    # ones are fused with chairs.
    cols = len(tids) * 2 + 1
    swatch = np.zeros((8, 8 * cols, 3), np.uint8)
    swatch[:, -8:] = (58, 58, 62)
    v, uv, f = [], [], []

    def quad(corners, col):
        f.append(np.array([[0, 1, 2], [0, 2, 3]]) + len(v) * 4)
        v.append(corners)
        uv.append([[(8 * col + 4) / (8 * cols), 0.5]] * 4)

    def sides(x0, y0, x1, y1, z0, z1, col):  # the four upright faces of a box, facing out
        quad([[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]], col)
        quad([[x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]], col)
        quad([[x1, y1, z0], [x0, y1, z0], [x0, y1, z1], [x1, y1, z1]], col)
        quad([[x0, y1, z0], [x0, y0, z0], [x0, y0, z1], [x0, y1, z1]], col)

    for i, tid in enumerate(tids):
        tb = tables[tid]
        colour = np.clip(cloth_rgb[tid] * cloth_gain[i], 0, 255)
        swatch[:, 16 * i:16 * i + 8], swatch[:, 16 * i + 8:16 * i + 16] = colour, colour * 0.8
        (a, c), (b_, d), zt = tb["min"], tb["max"], tb["top_m"]
        ground = float(-_above(h, np.array([[(a + b_) / 2, (c + d) / 2, 0.0]]), lo)[0])
        quad([[a + 0.03, c + 0.03, zt - 0.035], [b_ - 0.03, c + 0.03, zt - 0.035], [b_ - 0.03, d - 0.03, zt - 0.035], [a + 0.03, d - 0.03, zt - 0.035]], 2 * i)
        sides(a + 0.03, c + 0.03, b_ - 0.03, d - 0.03, zt - 0.30, zt - 0.035, 2 * i + 1)
        for lx in (a + 0.06, b_ - 0.09):
            for ly in (c + 0.06, d - 0.09):
                sides(lx, ly, lx + 0.03, ly + 0.03, ground, zt - 0.035, cols - 1)
    if v:
        pieces.append(("patch_tables", np.array(v, float).reshape(-1, 3), np.array(uv, float).reshape(-1, 2), np.concatenate(f), swatch))
    return pieces, {"floor_holes_m2": round(float(ok[lab].sum()) * FLOOR_CELL ** 2, 1), "floor_mended_m2": round(float((mend[seen] > 0.5).sum()) * FLOOR_CELL ** 2, 1),
                    "room_floor_rgb": room_goals, "board_change": [round(float(c), 2) for c in change], "floor_sound_m2": round(float(sound.sum()) * FLOOR_CELL ** 2, 1), "floor_copied_m2": round(float((have & ~sound & seen).sum()) * FLOOR_CELL ** 2, 1), "boards_run_along": "xy"[along],
                    "cloth_gain": {t.split("_")[-1]: round(float(g), 2) for t, g in zip(tids, cloth_gain)}}
