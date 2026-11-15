"""A Matterport model to world.json.

    python -m world.matterport zvKHR9DHNjJ la_mirada      # writes world/scenarios/la_mirada.json

The Model API (GraphQL, the hackathon keys in .env) gives the floor plan: wall lines with their doorways,
and each room as a ring of those walls with a label and a ceiling height. That is the rooms, doorways and
floors of the world, in the model's own frame (metres, Z up), so the MatterPak mesh and the tour line up
with it unchanged. The API has no furniture for these models (objectAnnotations is empty), so obstacles
and table tops are measured on the MatterPak mesh by world/mesh.py; without a mesh both lists are empty
and no job can be planned there.

`build` is the pure part (API record, optional mesh, to a world dict); `fetch` and `fetch_mesh` are the
network, kept in world/_scans/<name>/ (not committed). The API client is Pathfinder's.
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCANS = HERE / "_scans"
SCENARIOS = HERE / "scenarios"

QUERY = """query World($id: ID!) { model(id: $id) {
  id name address { address }
  floors { id label sequence
    vertices { id position { x y } }
    edges { id type thickness vertices { id }
            openings { id type label width height lowerElevation relativeCenter } } }
  rooms { id label floor { id } classifications { label confidence }
          dimensions(units: metric) { areaFloor height } ceiling(units: metric) { minHeight maxHeight }
          boundary { edges { id } } holes { edges { id } } }
  locations { id position { x y z } floor { id } }
} }"""

OUTSIDE = "outside"
CEILING_M = 2.4          # when the API has no height for a room
PASSAGE_MAX_M = 2.5      # nav treats a wider doorway as a bad reading, so an open side is cut into parts
DOCK_CLEAR_M = 0.45      # free floor wanted around the dock
DOCK_HEIGHT_M = 2.0      # anything lower than this is in the robot's way there
SKIP_ROOMS = {"void"}    # the API's label for wall cavities and unscanned space
# API frame (x, y, z up) to the tour's (x, z up, -y): the Showcase SDK is Y up
TO_MODEL = [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, -1.0, 0.0, 0.0]]


class NoPlan(ValueError):
    """The model has no floor plan the API can give: no rooms with walls."""


# ---------------------------------------------------------------------------------------------- network

def _client():
    """Pathfinder's Matterport client (world/pathfinder is its own project, so it is loaded by path)."""
    name = "_pathfinder_matterport"
    if name not in sys.modules:
        path = HERE / "pathfinder" / "backend" / "pipeline" / "matterport.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[name] = module
    return sys.modules[name]


def fetch(model_id: str, *, cache: Path | None = None) -> dict:
    """The model's floor plan record from the Model API. With `cache`, read from and saved to that file."""
    if cache is not None and cache.exists():
        return json.loads(cache.read_text())
    model = _client().graph(QUERY, id=model_id)["model"]
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(model, indent=1))
    return model


def fetch_mesh(model_id: str, dest: Path) -> Path:
    """The model's MatterPak OBJ (with its textures), downloaded into `dest` once."""
    obj, _ = _client().fetch_mesh(model_id, dest)
    return obj


# ---------------------------------------------------------------------------------------------- floor plan

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _ring(edge_ids: list, ends: dict) -> tuple:
    """(vertex ids in order around a room, the stub walls left over) from the room's unordered walls. A stub
    is a wall that juts into the room and ends there. The ring is None when the rest does not close one loop."""
    live, spurs = list(edge_ids), []
    while True:
        degree: dict = {}
        for e in live:
            for v in ends[e]:
                degree[v] = degree.get(v, 0) + 1
        loose = [e for e in live if any(degree[v] == 1 for v in ends[e])]
        if not loose:
            break
        spurs += loose
        live = [e for e in live if e not in loose]
    nxt: dict = {}
    for e in live:
        a, b = ends[e]
        nxt.setdefault(a, []).append(b)
        nxt.setdefault(b, []).append(a)
    if not nxt or any(len(v) != 2 for v in nxt.values()):
        return None, spurs
    start = next(iter(nxt))
    ring, prev, at = [start], None, start
    while len(ring) <= len(nxt):
        a, b = nxt[at]
        step = b if a == prev else a
        if step == start:
            break
        ring.append(step)
        prev, at = at, step
    return (ring if len(ring) == len(nxt) else None), spurs


def _area(poly: list) -> float:
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def inside(poly: list, x: float, y: float) -> bool:
    hit = False
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def _across(poly: list) -> float:
    """The room's extent across its longest wall (nav reads a hallway's width_m)."""
    best, axis = -1.0, (1.0, 0.0)
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
        length = math.hypot(bx - ax, by - ay)
        if length > best:
            best, axis = length, ((bx - ax) / length, (by - ay) / length)
    side = [-p[0] * axis[1] + p[1] * axis[0] for p in poly]
    return max(side) - min(side)


def layout(model: dict) -> dict:
    """Floors, rooms, doorways and wall segments from the API record. `walls` (not part of world.json) is
    what world/mesh.py masks out: [{"a", "b", "thickness_m", "floor"}]."""
    floors, floor_of, points, ends, edges = [], {}, {}, {}, {}
    for n, f in enumerate(sorted(model.get("floors") or [], key=lambda f: f.get("sequence") or 0)):
        fid = f"f{n + 1}"
        zs = sorted(l["position"]["z"] for l in model.get("locations") or []
                    if (l.get("floor") or {}).get("id") == f["id"] and l.get("position"))
        floors.append({"id": fid, "z": round(zs[len(zs) // 2], 3) if zs else 0.0, "label": f.get("label")})
        floor_of[f["id"]] = fid
        for v in f.get("vertices") or []:
            points[v["id"]] = (v["position"]["x"], v["position"]["y"])
        for e in f.get("edges") or []:
            ends[e["id"]] = tuple(v["id"] for v in e["vertices"])
            edges[e["id"]] = dict(e, floor=fid)

    rooms, sides, stubs, skipped, count = [], {}, {}, [], {}
    for r in model.get("rooms") or []:
        label = next((c["label"] for c in r.get("classifications") or [] if c.get("label")), None) or r.get("label")
        kind = _slug(label) if label else "room"
        count[kind] = count.get(kind, 0) + 1
    listed: dict = {}  # wall -> how many rooms of the record list it, the ones left out here included
    for r in model.get("rooms") or []:
        for e in (r.get("boundary") or {}).get("edges") or []:
            listed[e["id"]] = listed.get(e["id"], 0) + 1
    seen: dict = {}
    for r in model.get("rooms") or []:
        label = next((c["label"] for c in r.get("classifications") or [] if c.get("label")), None) or r.get("label")
        kind = _slug(label) if label else "room"
        seen[kind] = seen.get(kind, 0) + 1
        rid = kind if count[kind] == 1 else f"{kind}_{seen[kind]}"
        edge_ids = [e["id"] for e in (r.get("boundary") or {}).get("edges") or [] if e["id"] in ends]
        if kind in SKIP_ROOMS:
            continue
        ring, spurs = _ring(edge_ids, ends)
        if ring is None:
            skipped.append(rid)
            continue
        poly = [points[v] for v in ring]
        if _area(poly) < 0:
            poly.reverse()
        dims, ceil = r.get("dimensions") or {}, r.get("ceiling") or {}
        height = ceil.get("minHeight") or dims.get("height")
        room = {"id": rid, "type": kind, "floor": floor_of.get((r.get("floor") or {}).get("id"), floors[0]["id"] if floors else None),
                "polygon": [[round(x, 3), round(y, 3)] for x, y in poly],
                "ceiling_m": round(height, 2) if height else CEILING_M, "source": "api",
                "width_m": round(_across(poly), 2)}
        if not height:
            room["note"] = f"no height in the scan's record; {CEILING_M} m assumed"
        rooms.append(room)
        for e in edge_ids:
            if e in spurs:
                stubs[e] = rid
            else:
                sides.setdefault(e, []).append(rid)
    if not rooms:
        raise NoPlan(f"model {model.get('id')} has no rooms with walls in the Model API")

    ceiling = {r["id"]: r["ceiling_m"] for r in rooms}
    doorways, walls, stub_boxes = [], [], []
    for eid, e in edges.items():
        a, b = (points[v] for v in ends[eid])
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length < 1e-6:
            continue
        along = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
        between = sides.get(eid, [])
        blind = len(between) == 1 and listed.get(eid, 0) > 1   # the far side is space the record has no room for
        if len(between) == 1:
            between = [OUTSIDE, between[0]]
        passages = []  # (centre along the wall, width, header, step, note)
        if e.get("type") == "invisible":  # two rooms with no wall between them: the whole side is open
            parts = max(1, math.ceil(length / PASSAGE_MAX_M))
            head = min((ceiling[r] for r in between if r in ceiling), default=CEILING_M)
            passages = [((i + 0.5) * length / parts, length / parts, head, 0.0,
                         "open side between the two rooms" + (f", cut into {parts} parts" if parts > 1 else ""))
                        for i in range(parts)]
        else:
            walls.append({"a": list(a), "b": list(b), "thickness_m": e.get("thickness") or 0.15, "floor": e["floor"]})
            if eid in stubs:  # nav only walls off room outlines, so a wall inside a room is an obstacle
                half = walls[-1]["thickness_m"] / 2
                z = next(f["z"] for f in floors if f["id"] == e["floor"])
                stub_boxes.append({"id": f"wall_stub_{len(stub_boxes) + 1}", "room": stubs[eid], "source": "api", "box": {
                    "min": [round(min(a[0], b[0]) - half, 3), round(min(a[1], b[1]) - half, 3), z],
                    "max": [round(max(a[0], b[0]) + half, 3), round(max(a[1], b[1]) + half, 3), round(z + ceiling[stubs[eid]], 3)]}})
                continue
            for o in e.get("openings") or []:
                if o.get("type") not in ("doorway", "opening") or not o.get("width"):
                    continue
                low = o.get("lowerElevation") or 0.0
                head = low + o["height"] if o.get("height") else min((ceiling[r] for r in between if r in ceiling), default=CEILING_M)
                centre, width = (o.get("relativeCenter") if o.get("relativeCenter") is not None else 0.5) * length, o["width"]
                parts = math.ceil(width / PASSAGE_MAX_M) if o["type"] == "opening" else 1
                for i in range(parts):
                    passages.append((centre - width / 2 + (i + 0.5) * width / parts, width / parts, head, max(0.0, low),
                                     (o.get("label") or o["type"]) + (f", cut into {parts} parts" if parts > 1 else "")))
        if len(between) != 2:
            continue  # a wall no kept room touches
        for s, width, head, step, note in passages:
            doorways.append({"id": f"d{len(doorways) + 1}", "rooms": list(between),
                             "position": [round(a[0] + along[0] * s, 3), round(a[1] + along[1] * s, 3)],
                             "along": [round(along[0], 4), round(along[1], 4)], "width_m": round(width, 3),
                             "header_m": round(head, 3), "step_m": round(step, 3), "source": "closed" if blind else "api",
                             "note": note + ("; opens into a part of the building the scan has no room for, not to the "
                                             "outside, so it is closed to the robot" if blind else "")})
    return {"floors": floors, "rooms": rooms, "doorways": doorways, "walls": walls, "stubs": stub_boxes, "skipped": skipped}


# ---------------------------------------------------------------------------------------------- way out, dock

def _way_out(rooms: list, doorways: list) -> dict | None:
    """The widest outside door nav will take (0.45 to 2.5 m) on the lowest floor."""
    floor = {r["id"]: r["floor"] for r in rooms}
    outs = [d for d in doorways if d["rooms"][0] == OUTSIDE and d["source"] == "api" and 0.45 <= d["width_m"] <= PASSAGE_MAX_M]
    outs.sort(key=lambda d: (floor.get(d["rooms"][1], ""), -d["width_m"]))
    return outs[0] if outs else None


def _free_spot(room: dict, obstacles: list, floor_z: float, near: tuple | None = None) -> tuple:
    """(x, y, clearance) of a place to stand in the room: with `near`, the closest spot to it that has
    DOCK_CLEAR_M of free floor all round; without, or when the room has no such spot, the roomiest one.
    Free floor is inside the room's outline and off every obstacle that reaches into the robot's height."""
    import numpy as np
    from scipy import ndimage
    from world.mesh import _in_polygon
    cell = 0.05
    poly = np.array(room["polygon"], float)
    x0, y0 = poly.min(axis=0) - cell
    nx, ny = (np.ceil((poly.max(axis=0) - (x0, y0)) / cell).astype(int) + 2)
    cx, cy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * cell, y0 + (np.arange(ny) + 0.5) * cell)
    free = _in_polygon(cx, cy, room["polygon"])
    for o in obstacles:
        lo, hi = o["box"]["min"], o["box"]["max"]
        if lo[2] < floor_z + DOCK_HEIGHT_M and hi[2] > floor_z + 0.05:
            free &= ~((cx > lo[0] - cell) & (cx < hi[0] + cell) & (cy > lo[1] - cell) & (cy < hi[1] + cell))
    clearance = ndimage.distance_transform_edt(free) * cell
    roomy = clearance >= DOCK_CLEAR_M
    if near is not None and roomy.any():
        score = np.where(roomy, -np.hypot(cx - near[0], cy - near[1]), -np.inf)
    else:
        score = clearance
    i, j = np.unravel_index(np.argmax(score), score.shape)
    return float(cx[i, j]), float(cy[i, j]), float(clearance[i, j])


def _dock(plan: dict, obstacles: list, out: dict | None) -> tuple:
    """({"room", "pose"}, note): with a way out, the nearest roomy spot just inside it, facing in; with none,
    the roomiest spot of the room with the most doors."""
    z = {f["id"]: f["z"] for f in plan["floors"]}
    rooms = {r["id"]: r for r in plan["rooms"]}
    if out is not None:
        room = rooms[out["rooms"][1]]
        px, py = out["position"]
        nx, ny = -out["along"][1], out["along"][0]
        if not inside(room["polygon"], px + 0.3 * nx, py + 0.3 * ny):
            nx, ny = -nx, -ny
        x, y, clear = _free_spot(room, obstacles, z[room["floor"]], near=(px + nx, py + ny))
        yaw = math.atan2(ny, nx)
    else:
        doors: dict = {}
        for d in plan["doorways"]:
            if d["source"] == "api":
                for r in d["rooms"]:
                    doors[r] = doors.get(r, 0) + 1
        lowest = min(z.values())
        room = max((r for r in plan["rooms"] if z[r["floor"]] == lowest), key=lambda r: (doors.get(r["id"], 0), abs(_area(r["polygon"]))))
        x, y, clear = _free_spot(room, obstacles, z[room["floor"]])
        yaw = 0.0
    note = None if clear >= DOCK_CLEAR_M else f"the roomiest spot in {room['id']} has only {clear:.2f} m of free floor round it"
    return {"room": room["id"], "pose": [round(x, 3), round(y, 3), round(yaw, 4)], **({"note": note} if note else {})}


# ---------------------------------------------------------------------------------------------- the world

def build(model: dict, *, name: str | None = None, mesh: str | Path | None = None) -> dict:
    """The world.json dict for a Model API record (see QUERY). `mesh` is the MatterPak OBJ; with it the
    furniture becomes obstacles and the table and counter tops become `surface` anchors."""
    plan = layout(model)
    # one floor only: nav plans on a single flat map and nothing models stairs. The floor with the most rooms
    # is kept and becomes Z = 0
    per_floor = {f["id"]: sum(r["floor"] == f["id"] for r in plan["rooms"]) for f in plan["floors"]}
    floor = max(plan["floors"], key=lambda f: per_floor[f["id"]])
    others = [f for f in plan["floors"] if f is not floor and per_floor[f["id"]]]
    here = {r["id"] for r in plan["rooms"] if r["floor"] == floor["id"]} | {OUTSIDE}
    plan = dict(plan, floors=[floor], rooms=[r for r in plan["rooms"] if r["id"] in here],
                doorways=[d for d in plan["doorways"] if set(d["rooms"]) <= here],
                walls=[w for w in plan["walls"] if w["floor"] == floor["id"]],
                stubs=[o for o in plan["stubs"] if o["room"] in here])
    rooms, doorways, lift = plan["rooms"], plan["doorways"], floor["z"]
    obstacles, anchors, measured = list(plan["stubs"]), [], "no mesh was read, so there is no furniture and there are no anchors"
    if mesh is not None:
        from world import mesh as scan
        found = scan.furniture(mesh, plan)
        obstacles, anchors = obstacles + found["obstacles"], found["anchors"]
        measured = (f"furniture ({len(found['obstacles'])} boxes) and table tops ({len(anchors)}) measured on the MatterPak mesh "
                    "by world/mesh.py: anything standing between 0.1 and 2 m above the floor, away from the walls, "
                    "boxed on a 0.1 m grid")
    for o in obstacles:
        o["box"] = {k: [v[0], v[1], round(v[2] - lift, 2)] for k, v in o["box"].items()}
    for a in anchors:
        a["point"] = [a["point"][0], a["point"][1], round(a["point"][2] - lift, 3)]
    plan["floors"] = [dict(floor, z=0.0)]
    out = _way_out(rooms, doorways)
    no_door = ("The scan's record has no door to the outside (the entrance was most likely shut when it was scanned), so "
               "there is no way out: the robot starts inside and nothing can be carried out")
    address = (model.get("address") or {}).get("address")
    world = {
        "schema": "world/1",
        "id": name or _slug(model.get("name") or model["id"]),
        "frame": "metres, Z up, right handed; X and Y are the Matterport model's own, as the Model API and the MatterPak "
                 f"mesh give them, and Z is height above the floor ({lift:+.3f} m in the model)",
        "source": (f"read from Matterport model {model['id']}" + (f" ({address})" if address else "") +
                   " by world/matterport.py: rooms, doorways and ceilings from the Model API's floor plan; " + measured +
                   ". Room outlines follow the middle of each wall, not its inner face, so rooms read up to half a wall "
                   "(about 0.1 m) wider than they are" +
                   (f". Left out, their walls do not close a loop: {', '.join(plan['skipped'])}" if plan["skipped"] else "") +
                   (f". Only {floor.get('label') or floor['id']} is here, the floor with the most rooms; left out: " +
                    ", ".join(f"{f.get('label') or f['id']} ({per_floor[f['id']]} rooms)" for f in others) if others else "") +
                   ("" if out else ". " + no_door)),
        "mesh": str(mesh) if mesh is not None else None,
        "tour": {"matterport": model["id"], "to_model": [TO_MODEL[0], [0.0, 0.0, 1.0, round(lift, 3)], TO_MODEL[2]],
                 "note": "the world's X and Y are the model's, so this is the floor's height and the change from Z up to "
                         "the tour's Y up (x, y, z to x, z, -y); not yet checked in the tour viewer"},
        "floors": [{"id": f["id"], "z": f["z"]} for f in plan["floors"]],
        "rooms": rooms,
        "doorways": doorways,
        "obstacles": obstacles,
        "dock": _dock(plan, obstacles, out),
        "way_out": {"doorway": out["id"]} if out else {"doorway": None, "note": no_door},
        "anchors": anchors,
    }
    return world


def load(model_id: str, name: str, *, with_mesh: bool = True) -> dict:
    """Fetch (or reuse, from world/_scans/<name>/) and build."""
    scan = SCANS / name
    model = fetch(model_id, cache=scan / "api.json")
    obj = fetch_mesh(model_id, scan / "matterpak") if with_mesh else None
    world = build(model, name=name, mesh=obj)
    if obj is not None:
        world["mesh"] = str(obj.relative_to(HERE.parent))
    return world


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    model_id, name = argv[0], argv[1]
    world = load(model_id, name, with_mesh="--no-mesh" not in argv)
    out = SCENARIOS / f"{name}.json"
    out.write_text(json.dumps(world, indent=1) + "\n")
    print(f"{out.relative_to(HERE.parent)}: {len(world['rooms'])} rooms, {len(world['doorways'])} doorways, "
          f"{len(world['obstacles'])} obstacles, {len(world['anchors'])} anchors; dock in {world['dock']['room']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
