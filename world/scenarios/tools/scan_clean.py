"""Cleans a stitched room scan for showing: takes out what stands about on the floor (people, chairs, bags, boxes,
things left on tables), drops loose shards, patches the holes that leaves, and evens out the light and shade
the scanner's photos baked into the textures. Used by stitch_scan.py after it has measured the tables.

What is kept is decided by where a triangle is, not what it looks like: the floor, anything in a column that
has scan at wall height (walls, pillars, stairs), the measured table tops with their cloths and legs, the
world's other obstacles, and everything above head height. The plan's obstacles are not changed by this: a
chair removed here was never an obstacle to the planner, and still is not."""
import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

CELL = 0.10            # grid for "is there a wall in this column", metres
WALL_BAND = (1.9, 2.4)  # a column with scan in this height band, and most of the way up to it, is structure
WALL_BINS = 7
FLOOR_TOP = 0.07       # below this a triangle is floor
HEAD = 1.95            # at or above this nothing is clutter
CLOTH_M = 0.45         # a tablecloth hangs this far below the top
SHARD_M2 = 0.30        # a loose piece smaller than this is dropped
FLOOR_CELL = 0.04      # the floor picture used for patching and for reading the light
LIGHT_CELL = 0.12
EXPOSURE = 1.10
GAIN = (0.7, 10.0)     # how far a texel may be darkened or brightened
UNDER = 5              # the floor underlay is made of squares this many floor cells a side
HOLE_M2 = 3.0          # a gap in the floor up to this size is patched; larger ones are shafts and voids


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


def _in_table(c, zmax, f, pad=0.07):
    """The top of a table. Its cloth sides and legs are not kept: the scanner fused chairs and knees into them, so
    they are drawn fresh by relight_and_patch."""
    lo, hi = np.array(f["min"]) - pad, np.array(f["max"]) + pad
    return np.all((c[:, :2] >= lo) & (c[:, :2] <= hi), 1) & (zmax <= f["top_m"] + 0.015) & (c[:, 2] >= f["top_m"] - 0.05)


def remove_clutter(tiles: dict, tables: dict, keep_boxes: list, lo, hi, h) -> dict:
    """Drop the triangles of things standing about. `tables` is {id: {"min", "max", "top_m"}}; `keep_boxes` are
    other obstacles' boxes [(min xyz, max xyz)], kept whole, with no margin (they are traced by hand, and a margin keeps
    the chairs next to them). Returns counts for the report."""
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
    before = after = 0
    for t in tiles.values():
        tri = t["w"][t["idx"]]
        c, zmax = tri.mean(1), tri[:, :, 2].max(1)
        ij = _cells(c[:, :2], lo, shape, CELL)
        floor = zmax - (c[:, 2] - _above(h, c, lo)) < FLOOR_TOP
        keep = floor | (zmax >= HEAD) | wall[ij[:, 0], ij[:, 1]]
        safe = np.zeros(len(tri), bool)
        for f in tables.values():
            safe |= _in_table(c, zmax, f)
        keep |= safe
        for bl, bh in keep_boxes:  # kept, but not spared the shard test below: a stair is one piece, a broken glass rail is splinters
            keep |= np.all((c >= np.array(bl) - [0, 0, 0.1]) & (c <= np.array(bh) + [0, 0, 0.3]), 1)
        t["safe"] = safe | floor
        before += len(tri)
        after += int(keep.sum())
        t["idx"], t["safe"] = t["idx"][keep], t["safe"][keep]
    # loose shards: join the tiles' corners where they coincide, then drop every small piece that is not a table or obstacle
    allv = np.concatenate([t["w"] for t in tiles.values()])
    _, ids = np.unique(np.round(allv * 500).astype(np.int64), axis=0, return_inverse=True)
    ids = ids.ravel()
    off, faces, owner = 0, [], []
    for k, t in tiles.items():
        faces.append(ids[t["idx"] + off])
        owner.append(np.full(len(t["idx"]), len(owner)))
        off += len(t["w"])
    faces = np.concatenate(faces)
    n = int(ids.max()) + 1
    graph = coo_matrix((np.ones(len(faces) * 2, bool), (np.r_[faces[:, 0], faces[:, 1]], np.r_[faces[:, 1], faces[:, 2]])), shape=(n, n))
    _, label = connected_components(graph, directed=False)
    comp = label[faces[:, 0]]
    tri_all = np.concatenate([t["w"][t["idx"]] for t in tiles.values()])
    area = 0.5 * np.linalg.norm(np.cross(tri_all[:, 1] - tri_all[:, 0], tri_all[:, 2] - tri_all[:, 0]), axis=1)
    small = (np.bincount(comp, weights=area)[comp] < SHARD_M2) & ~np.concatenate([t["safe"] for t in tiles.values()])
    at = 0
    for t in tiles.values():
        m = len(t["idx"])
        t["idx"] = t["idx"][~small[at:at + m]]
        t.pop("safe")
        at += m
    return {"triangles": before, "after_clutter": after, "after_shards": after - int(small.sum()), "wall_cells": int(wall.sum())}


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


LUMA = np.array([0.299, 0.587, 0.114])


def _flatten(img, valid, goal, sigma, limit):
    """Per-channel gain that brings a one-material surface (picture `img` [X, Y, 3] over cells `valid`) to the colour
    `goal`: goal over the local mean, with brightness held to `limit` and the colour shift to a narrower range."""
    local = np.stack([ndimage.gaussian_filter(_fill(ndimage.median_filter(img[..., c], 3), valid), sigma) for c in range(3)], -1)
    raw = goal / np.maximum(local, 1.0)
    light = (goal @ LUMA) / np.maximum(local @ LUMA, 1.0)
    cast = np.abs(raw / light[..., None] - 1).max(-1)  # how far the light's colour is from the goal's
    return np.clip(light, *limit)[..., None] * np.clip(raw / light[..., None], 0.6, 1.6), local @ LUMA, cast


def relight_and_patch(tiles: dict, images: dict, rooms: list, tables: dict, lo, hi, h) -> tuple[list, dict]:
    """Evens the baked light in `images` ({tile: uint8 array [H, W, 3]}, changed in place) and returns the patch
    pieces [(name, vertices, uv, faces, image)] for the holes: one for the floor, one for the table tops.
    `rooms` are [(min xy, max xy)] in the world's frame: inside one, the floor is brought to one colour.

    The floor of a room is one material and so is a tablecloth, so on those the light can be read straight off the
    picture: the local mean colour is the light, and dividing it out leaves the grain. Everything else (walls,
    pillars, stairs, cloth sides) gets a gentler, brightness-only correction taken from the floor near it."""
    shape = tuple(np.ceil((hi - lo) / FLOOR_CELL).astype(int) + 1)
    size = shape[0] * shape[1]
    acc = {"floor": [np.zeros((*shape, 3)), np.zeros(shape)], "top": [np.zeros((*shape, 3)), np.zeros(shape)]}
    fx, fy = np.meshgrid(lo[0] + (np.arange(shape[0]) + 0.5) * FLOOR_CELL, lo[1] + (np.arange(shape[1]) + 0.5) * FLOOR_CELL, indexing="ij")
    owner = np.full(shape, -1)  # which table's footprint a cell is in
    near = np.zeros(shape, bool)  # in a table's own shade
    tids = list(tables)
    for i, tid in enumerate(tids):
        f = tables[tid]
        owner[(fx > f["min"][0]) & (fx < f["max"][0]) & (fy > f["min"][1]) & (fy < f["max"][1])] = i
        near |= (fx > f["min"][0] - 0.25) & (fx < f["max"][0] + 0.25) & (fy > f["min"][1] - 0.25) & (fy < f["max"][1] + 0.25)
    tops = np.array([tables[t]["top_m"] for t in tids] + [1e9])

    def kinds(pos, level):
        """(on the floor, on a table top) for points with their triangles' levelness."""
        ij = _cells(pos[:, :2], lo, shape, FLOOR_CELL)
        fl = level & (np.abs(_above(h, pos, lo)) < FLOOR_TOP)
        top = level & ~fl & (np.abs(pos[:, 2] - tops[owner[ij[:, 0], ij[:, 1]]]) < 0.03)
        return ij, fl, top

    def level_of(t):
        tri = t["w"][t["idx"]]
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        return np.abs(nrm[:, 2]) > 0.9 * (np.linalg.norm(nrm, axis=1) + 1e-12)

    for k, t in tiles.items():
        img, up = images[k], level_of(t)
        for px, py, pos, ti in _texels(t, *img.shape[1::-1]):
            ij, fl, top = kinds(pos, up[ti])
            for name, m in (("floor", fl), ("top", top)):
                if m.any():
                    flat, col = ij[m, 0] * shape[1] + ij[m, 1], img[py[m], px[m]].astype(float)
                    for ch in range(3):
                        acc[name][0][..., ch] += np.bincount(flat, weights=col[:, ch], minlength=size).reshape(shape)
                    acc[name][1] += np.bincount(flat, minlength=size).reshape(shape)
    seen, seen_top = acc["floor"][1] > 0, (acc["top"][1] > 0) & (owner >= 0)
    floor = acc["floor"][0] / np.maximum(acc["floor"][1], 1)[..., None]
    top = acc["top"][0] / np.maximum(acc["top"][1], 1)[..., None]

    # what colour each stretch of floor should be: one colour per room, and outside the rooms the brighter end of
    # what is around (on a coarser grid; the floor there may be another material)
    open_ = seen & ~near
    b = round(LIGHT_CELL / FLOOR_CELL)
    cs = (shape[0] // b, shape[1] // b)
    block = lambda a: a[:cs[0] * b, :cs[1] * b].reshape(cs[0], b, cs[1], b, *a.shape[2:]).sum((1, 3))
    n = block(open_.astype(float))
    okc = n >= b * b // 2
    mean = block(floor * open_[..., None]) / np.maximum(n, 1)[..., None]
    cx, cy = np.meshgrid(lo[0] + (np.arange(cs[0]) + 0.5) * LIGHT_CELL, lo[1] + (np.arange(cs[1]) + 0.5) * LIGHT_CELL, indexing="ij")
    wide = np.stack([ndimage.gaussian_filter(_fill(mean[..., c], okc), 8.0) for c in range(3)], -1)
    goal = np.stack([ndimage.percentile_filter(wide[..., c], 70, size=65) for c in range(3)], -1)
    for rl, rh in rooms:
        inside = (cx > rl[0]) & (cx < rh[0]) & (cy > rl[1]) & (cy < rh[1])
        if (inside & okc).sum() > 50:
            lum = mean[inside & okc] @ LUMA
            goal[inside] = np.median(mean[inside & okc][(lum > np.percentile(lum, 60)) & (lum < np.percentile(lum, 90))], 0)  # the well-lit floor
    goal = np.stack([ndimage.gaussian_filter(goal[..., c], 3.0) for c in range(3)], -1)
    broad = np.sqrt(np.clip((goal @ LUMA) / np.maximum(wide @ LUMA, 1.0), *GAIN)) * EXPOSURE
    broad[ndimage.distance_transform_edt(~okc) * LIGHT_CELL > 2.0] = EXPOSURE
    broad = ndimage.gaussian_filter(broad, 2.0)
    goal_fine = np.stack([ndimage.zoom(goal[..., c], (shape[0] / cs[0], shape[1] / cs[1]), order=1) for c in range(3)], -1)[:shape[0], :shape[1]]
    fine, floor_light, cast = _flatten(floor, open_, goal_fine, 3.0, GAIN)
    fine *= EXPOSURE
    # Deep shade holds brightness but hardly any colour, and a pool of sunlight is tinted: multiplied up or down they
    # come out blotchy yellow. There the floor is rebuilt instead from the room's floor colour and the texel's
    # brightness against its surroundings, which keeps the boards' grain. `deep` is how far to go over to that:
    # from none at 2.5x brightening to all at 5x, or from a colour cast of 15% to one of 40%.
    need = (goal_fine @ LUMA) / np.maximum(floor_light, 1.0)
    deep = np.maximum(np.clip((need - 2.5) / 2.5, 0, 1), np.clip((cast - 0.15) / 0.25, 0, 1))
    deep = ndimage.gaussian_filter(np.where(open_, deep, 0.0), 1.5)
    # the cloths are all the same cloth: every table top goes to the colour of the well-lit ones
    cloth = np.array([np.median(top[seen_top & (owner == i)], 0) for i in range(len(tids)) if (seen_top & (owner == i)).sum() > 50] or [[200.0, 110.0, 40.0]])
    cloth_goal = np.percentile(cloth, 70, axis=0)
    tfine = _flatten(top, seen_top, cloth_goal, 3.0, (0.6, 6.0))[0] * EXPOSURE
    side = np.array([float(np.clip((cloth_goal @ LUMA) / max(np.median(top[seen_top & (owner == i)], 0) @ LUMA, 1.0), 0.7, 3.0)) * EXPOSURE
                     if (seen_top & (owner == i)).sum() > 50 else EXPOSURE for i in range(len(tids))] + [EXPOSURE])
    skirt = np.full(shape, -1)  # a table's footprint with the cloth's overhang
    for i, tid in enumerate(tids):
        f = tables[tid]
        skirt[(fx > f["min"][0] - 0.1) & (fx < f["max"][0] + 0.1) & (fy > f["min"][1] - 0.1) & (fy < f["max"][1] + 0.1)] = i

    def gain_at(pos, level):
        ij, fl, on_top = kinds(pos, level)
        up = _above(h, pos, lo)
        g = ndimage.map_coordinates(broad, [(pos[:, 0] - lo[0]) / LIGHT_CELL - 0.5, (pos[:, 1] - lo[1]) / LIGHT_CELL - 0.5], order=1, mode="nearest")
        g = 1 + (g - 1) * np.clip((4.0 - up) / 1.5, 0, 1)  # full strength up to 2.5 m, none above 4 m
        who = skirt[ij[:, 0], ij[:, 1]]
        cloth_side = (who >= 0) & (pos[:, 2] < tops[who] + 0.05) & ~fl
        g[cloth_side] = side[who[cloth_side]]
        g = np.repeat(g[:, None], 3, 1)
        g[fl] = fine[ij[fl, 0], ij[fl, 1]]
        g[on_top] = tfine[ij[on_top, 0], ij[on_top, 1]]
        mix = np.zeros(len(pos))
        mix[fl] = deep[ij[fl, 0], ij[fl, 1]]
        return g, mix, goal_fine[ij[:, 0], ij[:, 1]] * EXPOSURE, 1.0 / np.maximum(floor_light[ij[:, 0], ij[:, 1]], 1.0)

    for k, t in tiles.items():
        img, up = images[k], level_of(t)
        H, W = img.shape[:2]
        g, mix, tone, inv = np.full((H, W, 3), np.nan), np.zeros((H, W)), np.zeros((H, W, 3)), np.zeros((H, W))
        for px, py, pos, ti in _texels(t, W, H):
            g[py, px], mix[py, px], tone[py, px], inv[py, px] = gain_at(pos, up[ti])
        done = ~np.isnan(g[..., 0])
        if done.any() and not done.all():  # carry all of it into the gaps between charts, or seams go dark
            i = tuple(ndimage.distance_transform_edt(~done, return_distances=False, return_indices=True))
            g, mix, tone, inv = g[i], mix[i], tone[i], inv[i]
        src = img.astype(float)
        plain = src * np.nan_to_num(g, nan=1.0)
        grain = np.clip((src @ LUMA) * inv, 0.55, 1.5)[..., None] * tone
        images[k] = np.clip(plain * (1 - mix[..., None]) + grain * mix[..., None], 0, 255).astype(np.uint8)

    # patches. Floor: the floor picture with its gaps filled from their edges, laid just under the scan in the gaps only
    grain = np.clip((floor @ LUMA) / np.maximum(floor_light, 1.0), 0.55, 1.5)[..., None] * goal_fine * EXPOSURE
    lit = np.clip(floor * fine * (1 - deep[..., None]) + grain * deep[..., None], 0, 255)
    filled = np.stack([_fill(lit[..., c], seen) for c in range(3)], -1)
    soft = np.stack([ndimage.gaussian_filter(filled[..., c], 2.0) for c in range(3)], -1)
    picture = np.where(seen[..., None], filled, soft).astype(np.uint8)
    lab, count = ndimage.label(~seen)
    area = ndimage.sum(np.ones(shape), lab, index=np.arange(1, count + 1)) * FLOOR_CELL ** 2
    ok = np.zeros(count + 1, bool)
    ok[1:] = area < HOLE_M2
    ok[np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])] = False
    # laid under all of the floor, not only the gaps: the tiles do not meet exactly, and the cracks between them
    # are thinner than a cell. In blocks of UNDER cells, so it stays a few thousand squares.
    want = seen | ok[lab]
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

    # tables: a sheet in the cloth's colour just under each top, closing the gaps where things stood, and fresh cloth
    # sides and legs in place of the scanned ones. Three flat colours: top, sides (a little darker), legs.
    swatch = np.zeros((8, 24, 3), np.uint8)
    swatch[:, :8], swatch[:, 8:16], swatch[:, 16:] = np.clip(cloth_goal * EXPOSURE, 0, 255), np.clip(cloth_goal * EXPOSURE * 0.82, 0, 255), (58, 58, 62)
    v, uv, f = [], [], []

    def quad(corners, u):
        f.append(np.array([[0, 1, 2], [0, 2, 3]]) + len(v) * 4)
        v.append(corners)
        uv.append([[u, 0.5]] * 4)

    def sides(x0, y0, x1, y1, z0, z1, u):  # the four upright faces of a box, facing out
        quad([[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]], u)
        quad([[x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]], u)
        quad([[x1, y1, z0], [x0, y1, z0], [x0, y1, z1], [x1, y1, z1]], u)
        quad([[x0, y1, z0], [x0, y0, z0], [x0, y0, z1], [x0, y1, z1]], u)

    for tid in tids:
        tb = tables[tid]
        (a, c), (b_, d), zt = tb["min"], tb["max"], tb["top_m"]
        ground = float(-_above(h, np.array([[(a + b_) / 2, (c + d) / 2, 0.0]]), lo)[0])
        quad([[a - 0.04, c - 0.04, zt - 0.006], [b_ + 0.04, c - 0.04, zt - 0.006], [b_ + 0.04, d + 0.04, zt - 0.006], [a - 0.04, d + 0.04, zt - 0.006]], 1 / 6)
        sides(a - 0.04, c - 0.04, b_ + 0.04, d + 0.04, zt - CLOTH_M, zt - 0.006, 0.5)
        for lx in (a + 0.05, b_ - 0.08):
            for ly in (c + 0.05, d - 0.08):
                sides(lx, ly, lx + 0.03, ly + 0.03, ground, zt - CLOTH_M, 5 / 6)
    if v:
        pieces.append(("patch_tables", np.array(v, float).reshape(-1, 3), np.array(uv, float).reshape(-1, 2), np.concatenate(f), swatch))
    return pieces, {"floor_holes_m2": round(float(ok[lab].sum()) * FLOOR_CELL ** 2, 1), "deep_shade_m2": round(float((deep[open_] > 0.5).sum()) * FLOOR_CELL ** 2, 1), "tables_redrawn": len(tids),
                    "floor_gain": [round(float((fine @ LUMA)[open_].min()), 2), round(float((fine @ LUMA)[open_].max()), 2)],
                    "table_gain": [round(float((tfine @ LUMA)[seen_top].min()), 2), round(float((tfine @ LUMA)[seen_top].max()), 2)]}
