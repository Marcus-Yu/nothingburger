"""Building pre-pass: clean doorway widths, room graph, corridors, demands.

Reads only world.json (a dict) and the task list. No robot yet.
"""
from __future__ import annotations

import heapq
import math

WIDTH_MIN_M = 0.45
WIDTH_MAX_M = 2.5
OUTSIDE = "outside"


def clean_doorways(world: dict) -> list[dict]:
    """One record per doorway: id, width_m, status ("ok", "dropped", "closed"), note.

    A width under 0.45 m or over 2.5 m is a bad reading. The workflow re-measures
    it from the mesh; that is not implemented, so with or without a mesh the
    doorway is marked "dropped" and treated as impassable.
    """
    out = []
    for d in world.get("doorways", []):
        w = d.get("width_m")
        status, note = "ok", ""
        if d.get("source") in ("closed", "dropped"):
            status = d["source"]
            note = f"world.json marks it {status}; impassable"
        elif not isinstance(w, (int, float)) or isinstance(w, bool) or not (WIDTH_MIN_M <= w <= WIDTH_MAX_M):
            status = "dropped"
            why = "no mesh to re-measure from" if world.get("mesh") is None else "mesh re-measure not implemented"
            note = f"width {w!r} outside {WIDTH_MIN_M}-{WIDTH_MAX_M} m; {why}; impassable"
        out.append({"id": d["id"], "rooms": list(d["rooms"]), "width_m": w, "status": status,
                    "source": d.get("source"), "note": note})
    return out


def passable_doorways(world: dict) -> list[dict]:
    ok = {c["id"] for c in clean_doorways(world) if c["status"] == "ok"}
    return [d for d in world.get("doorways", []) if d["id"] in ok]


def _long_axis(polygon) -> tuple[tuple[float, float], float]:
    """Unit direction of the polygon's longest edge, and its extent across that."""
    best, axis = -1.0, (1.0, 0.0)
    n = len(polygon)
    for i in range(n):
        ax, ay = polygon[i][0], polygon[i][1]
        bx, by = polygon[(i + 1) % n][0], polygon[(i + 1) % n][1]
        length = math.hypot(bx - ax, by - ay)
        if length > best:
            best, axis = length, ((bx - ax) / length, (by - ay) / length)
    nx, ny = -axis[1], axis[0]
    across = [p[0] * nx + p[1] * ny for p in polygon]
    return axis, max(across) - min(across)


def hallway_width(room: dict) -> float:
    w = room.get("width_m")
    if isinstance(w, (int, float)) and w > 0:
        return float(w)
    return _long_axis(room["polygon"])[1]


def _graph(world: dict):
    rooms = {r["id"]: r for r in world["rooms"]}
    adj: dict[str, list] = {}
    for d in passable_doorways(world):
        a, b = d["rooms"]
        weight, limited = float(d["width_m"]), None
        for rid in (a, b):
            room = rooms.get(rid)
            if room is not None and room.get("type") == "hallway":
                hw = hallway_width(room)
                if hw < weight:
                    weight, limited = hw, rid
        edge = {"doorway": d, "weight": weight, "limited_by": limited}
        adj.setdefault(a, []).append((b, edge))
        adj.setdefault(b, []).append((a, edge))
    return rooms, adj


def _widest_path(adj, src, dst, skip_door=None):
    """Maximin path (Dijkstra with min in place of +); ties go to fewer doors.

    Returns (bottleneck width, rooms, edges) or None.
    """
    if src == dst:
        return math.inf, [src], []
    best = {src: (math.inf, 0)}
    heap = [(-math.inf, 0, src, [src], [])]
    while heap:
        negw, hops, node, rooms, edges = heapq.heappop(heap)
        if node == dst:
            return -negw, rooms, edges
        if (best[node][0], -best[node][1]) > (-negw, -hops):
            continue
        for other, edge in adj.get(node, []):
            if edge["doorway"]["id"] == skip_door or other in rooms:
                continue
            w = min(-negw, edge["weight"])
            cand = (w, hops + 1)
            old = best.get(other)
            if old is None or (w, -(hops + 1)) > (old[0], -old[1]):
                best[other] = cand
                heapq.heappush(heap, (-w, hops + 1, other, rooms + [other], edges + [edge]))
    return None


def _corridor(trip, rooms_by_id, path, reason="no passable doorway sequence joins the two rooms"):
    if path is None:
        return {"trip": trip, "rooms": [], "doorways": [], "bottleneck": None, "blocked": True, "reason": reason}
    _, rooms, edges = path
    bottleneck = None
    for e in edges:
        if bottleneck is None or e["weight"] < bottleneck["width_m"]:
            bottleneck = {"doorway": e["doorway"]["id"], "width_m": e["weight"]}
            if e["limited_by"]:
                bottleneck["limited_by"] = e["limited_by"]
    if not edges:
        room = rooms_by_id.get(rooms[0])
        if room is not None and room.get("type") == "hallway":
            bottleneck = {"doorway": None, "width_m": hallway_width(room), "limited_by": room["id"]}
    doors = [e["doorway"] for e in edges]
    headers = [d["header_m"] for d in doors if isinstance(d.get("header_m"), (int, float))]
    steps = [d["step_m"] for d in doors if isinstance(d.get("step_m"), (int, float))]
    floors = {rooms_by_id[r].get("floor") for r in rooms if r in rooms_by_id}
    turns = []
    for i, rid in enumerate(rooms):
        room = rooms_by_id.get(rid)
        if room is None or room.get("type") != "hallway":
            continue
        axis, _ = _long_axis(room["polygon"])
        for j in (i - 1, i):  # the doorway entering this hallway and the one leaving it
            if 0 <= j < len(doors):
                al = doors[j]["along"]
                norm = math.hypot(al[0], al[1]) or 1.0
                if abs(al[0] * axis[0] + al[1] * axis[1]) / norm > 0.7:  # door sits in a side wall
                    turns.append({"hallway": rid, "doorway": doors[j]["id"], "width_m": hallway_width(room)})
    return {"trip": trip, "rooms": rooms, "doorways": [d["id"] for d in doors], "bottleneck": bottleneck,
            "header_m": min(headers) if headers else None, "step_m": max(steps) if steps else 0.0,
            "changes_floor": len(floors) > 1, "turns": turns}


def way_out_path(world, adj, src):
    """Widest path from room `src` that ends by crossing the way-out doorway."""
    door_id = (world.get("way_out") or {}).get("doorway")
    door = next((d for d in passable_doorways(world) if d["id"] == door_id), None)
    if door is None:
        return None, f"way-out doorway {door_id!r} is missing, closed or dropped"
    best = None
    for inner, outer in (door["rooms"], door["rooms"][::-1]):
        if inner == OUTSIDE:
            continue
        p = _widest_path(adj, src, inner, skip_door=door_id)
        if p is None:
            continue
        edge = next(e for o, e in adj[inner] if e["doorway"]["id"] == door_id)
        cand = (min(p[0], edge["weight"]), p[1] + [outer], p[2] + [edge])
        key = (cand[0], outer == OUTSIDE, -len(cand[2]))
        if best is None or key > best[0]:
            best = (key, cand)
    if best is None:
        return None, "no passable doorway sequence reaches the way out"
    return best[1], ""


def corridors(world: dict, tasks: list) -> dict:
    rooms, adj = _graph(world)
    anchors = {a["id"]: a for a in world.get("anchors", [])}
    dock_room = world["dock"]["room"]
    out = []
    for t in tasks:
        anchor = anchors.get(t.get("anchor"))
        if anchor is None:
            if t.get("anchor") is not None:
                out.append(_corridor(f"dock->{t['id']}", rooms, None, f"anchor {t.get('anchor')!r} is not in the world"))
            continue
        out.append(_corridor(f"dock->{t['id']}", rooms, _widest_path(adj, dock_room, anchor["room"])))
        if t.get("carries"):
            path, reason = way_out_path(world, adj, anchor["room"])
            out.append(_corridor(f"{t['id']}->way_out", rooms, path, reason) if path
                       else _corridor(f"{t['id']}->way_out", rooms, None, reason))
    live = [c for c in out if not c.get("blocked")]
    necks = [c["bottleneck"] for c in live if c["bottleneck"]]
    neck = min(necks, key=lambda b: b["width_m"]) if necks else None
    headers = [c["header_m"] for c in live if c["header_m"] is not None]
    turns = [t["width_m"] for c in live for t in c["turns"]]
    demands = {
        "narrowest_m": neck["width_m"] if neck else None,
        "narrowest_doorway": neck["doorway"] if neck else None,
        "lowest_header_m": min(headers) if headers else None,
        "tallest_step_m": max([c["step_m"] for c in live], default=0.0),
        "tightest_turn_m": min(turns) if turns else None,
        "changes_floor": any(c["changes_floor"] for c in live),
    }
    return {"corridors": out, "demands": demands, "doorways": clean_doorways(world)}
