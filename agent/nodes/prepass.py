"""Step 1, the building pre-pass: what the building demands before a robot exists."""
from __future__ import annotations

from ..tools import nav

# Half the narrowest base width in the catalog. composer.api exposes part names, not card dimensions,
# so this is a parameter (state["prepass_radius_m"]) with a default, not a value read from the cards.
DEFAULT_RADIUS_M = 0.20


def step(state: dict) -> dict:
    """Reads state["world"], state["tasks"], optional state["prepass_radius_m"].
    Writes state["building"] = {"corridors", "demands", "doorways", "free_floor": {task id: {...}}, "anchors": {...}}."""
    world, tasks = state["world"], state["tasks"]
    radius = float(state.get("prepass_radius_m") or DEFAULT_RADIUS_M)
    out = nav.corridors(world, tasks)
    anchors = {a["id"]: a for a in world.get("anchors", [])}
    rooms = {r["id"]: r for r in world.get("rooms", [])}
    floors = {f["id"]: f.get("z", 0.0) for f in world.get("floors", [])}
    free, poses = {}, {}
    for t in tasks:
        a = anchors.get(t.get("anchor"))
        if a is None:
            continue
        free[t["id"]] = dict(nav.free_floor(world, a["id"], radius_m=radius), radius_m=radius)
        room = rooms.get(a.get("room"), {})
        floor_z = float(floors.get(room.get("floor"), 0.0))
        poses[t["id"]] = {"anchor": a["id"], "point": a["point"], "normal": a.get("normal"), "axis": a.get("axis"),
                          "height_above_floor_m": round(float(a["point"][2]) - floor_z, 3),
                          "ceiling_m": room.get("ceiling_m"), "source": a.get("source")}
    building = {"corridors": out["corridors"], "demands": out["demands"], "doorways": out.get("doorways", []),
                "free_floor": free, "anchors": poses, "radius_m": radius}
    return {**state, "building": building}
