"""Step 2, the requirements ledger: the building and the demo turned into numbers (requirements.json).

Only what is relative to the object carries over from a demo; where the object is comes from the building.
Requirements are kept per task; only the building rows (task: null) are shared.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ..tools import nav

OBJECT_CARDS = Path(__file__).resolve().parents[2] / "catalog" / "object"

SIDE_MARGIN_M = 0.05      # a side, off the narrowest passage and off the hallway at a turn
HEADER_MARGIN_M = 0.05
OPENING_MARGIN_M = 0.01   # object width plus this
WIPE_INSET_M = 0.05
WIPE_LANE_M = 0.15
WIPE_STROKE_MAX_M = 0.55  # a longer stroke is cut in two at its middle and the surface wiped as two bands
PRESS_DEFAULT_N = 10.0
PRESS_TOLERANCE_N = 2.0
REACH_TOLERANCE_M = 0.01
FREE_FLOOR_TOLERANCE_M = 0.05
FRICTION = 0.5            # pinch hold: fingers on the object
SAFETY = 1.5
G = 9.81
DEMO_NEAR_M = 0.15        # a re-anchored work pose farther than this from every target is flagged


def object_card(name: str) -> dict | None:
    path = OBJECT_CARDS / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def _r(v, n=4):
    return [round(float(x) + 0.0, n) for x in v]


def _row(rid, task, quantity, value, unit, tolerance, source, **extra):
    return {"id": rid, "task": task, "quantity": quantity, "value": value, "unit": unit, "tolerance": tolerance,
            "source": source, **extra}


# ------------------------------------------------------------------------------- fixture frame

def fixture_frame(anchor: dict) -> tuple[np.ndarray, np.ndarray, bool]:
    """(R, origin, yaw_free). Same rule as the demo frame: origin at the anchor, z out of its surface, x
    horizontal, world Z up. On a horizontal anchor (normal along Z) x has no preferred heading: it is taken
    as world X and yaw_free is True, so everything is stated up to a rotation about the normal."""
    z = _unit(anchor.get("normal") or [0, 0, 1])
    up = np.array([0.0, 0.0, 1.0])
    x = np.cross(up, z)
    yaw_free = float(np.linalg.norm(x)) < 1e-6
    x = np.array([1.0, 0.0, 0.0]) if yaw_free else _unit(x)
    y = np.cross(z, x)
    return np.column_stack([x, y, z]), np.asarray(anchor["point"], dtype=float), yaw_free


def reanchor(demo: dict, anchor: dict) -> dict:
    """The demo's hand path and approach direction in the building: T_world_fixture . T_fixture_hand
    (positions only; the hand-to-gripper transform is gap G12 and is not applied)."""
    R, origin, yaw_free = fixture_frame(anchor)
    path = [{"t": s["t"], "phase": s["phase"], "p": _r(origin + R @ np.asarray(s["p"], dtype=float))}
            for s in demo.get("path", [])]
    approach = demo.get("approach_direction")
    return {"path": path, "approach_direction": _r(R @ _unit(approach)) if approach else None, "yaw_free": yaw_free}


# ------------------------------------------------------------------------------- reach targets

def _tool_axis(anchor):
    return _r(-_unit(anchor.get("normal") or [0, 0, 1]))


def twist_targets(anchor: dict, card: dict | None) -> list:
    """The grasp point: the anchor's point moved out along its normal by half the object's size.
    The tool points into the fixture (against the outward normal)."""
    half = 0.5 * float((card or {}).get("width_m") or 0.0)
    p = np.asarray(anchor["point"], dtype=float) + half * _unit(anchor.get("normal") or [0, 0, 1])
    return [{"point": _r(p), "tool_axis": _tool_axis(anchor), "held_axes": ["position", "tool_axis"]}]


def pick_targets(anchor: dict) -> list:
    return [{"point": _r(anchor["point"]), "tool_axis": _tool_axis(anchor), "held_axes": ["position", "tool_axis"]}]


def wipe_targets(anchor: dict, side=None) -> list:
    """Stroke end points over the anchor's `extent` polygon inset 0.05 m, lanes 0.15 m apart, as a
    serpentine: targets 2k and 2k+1 are the two ends of stroke k. Lanes step along the polygon's longest
    edge and each stroke runs across it (yaw is free on a horizontal anchor; this is the choice that keeps
    every stroke as short as it can be for a base standing along the long side). A stroke longer than
    WIPE_STROKE_MAX_M is cut at its middle: all the near halves come first, then all the far halves. `side` is the free-floor
    side: the first stroke starts at the end nearer to it. The extent is taken as convex."""
    extent = [[float(p[0]), float(p[1])] for p in anchor.get("extent") or []]
    if len(extent) < 3:
        return pick_targets(anchor)
    z = float(anchor["point"][2])
    pts = np.asarray(extent)
    edges = np.roll(pts, -1, axis=0) - pts
    u = _unit(edges[int(np.argmax(np.linalg.norm(edges, axis=1)))])   # lanes step along u
    v = np.array([-u[1], u[0]])                                       # strokes run along v
    if side is not None and float(np.linalg.norm(side)) > 1e-6 and float(np.dot(v, side[:2])) < 0:
        v = -v                                                        # v points at the free floor
    s = pts @ u
    lo, hi = float(s.min()) + WIPE_INSET_M, float(s.max()) - WIPE_INSET_M
    if hi < lo:
        return pick_targets(anchor)
    n = int(math.floor((hi - lo) / WIPE_LANE_M + 1e-9)) + 1
    start = lo + ((hi - lo) - (n - 1) * WIPE_LANE_M) / 2              # centre the lanes in the inset span
    axis, lanes = _tool_axis(anchor), []
    for k in range(n):
        sk = start + k * WIPE_LANE_M
        cuts = []
        for a, e in zip(pts, edges):                                  # where the lane crosses the polygon
            du = float(e @ u)
            if abs(du) < 1e-12:
                continue
            f = (sk - float(a @ u)) / du
            if -1e-9 <= f <= 1 + 1e-9:
                cuts.append(float((a + f * e) @ v))
        if len(cuts) < 2 or max(cuts) - min(cuts) < 2 * WIPE_INSET_M:
            continue
        lanes.append((sk, max(cuts) - WIPE_INSET_M, min(cuts) + WIPE_INSET_M))
    # A deep surface is wiped as two bands, the near half and then the far half, so that each stroke is short
    # enough to do from the side it is nearer to (a table with floor on both sides) without the arm's elbow
    # having to come down across the whole surface.
    deep = any(near - far > WIPE_STROKE_MAX_M for _, near, far in lanes)
    bands = [lambda near, far: (near, (near + far) / 2), lambda near, far: (far, (near + far) / 2)] if deep else [lambda near, far: (near, far)]
    out = []
    for band in bands:
        for sk, near, far in lanes:
            a, b = band(near, far)
            for c in ([a, b] if len(out) // 2 % 2 == 0 else [b, a]):
                p = sk * u + c * v
                out.append({"point": _r([p[0], p[1], z]), "tool_axis": axis, "held_axes": ["position", "tool_axis"]})
    return out or pick_targets(anchor)


def _target_floors(world: dict, anchor: dict, targets: list, radius_m: float, at_anchor: dict) -> None:
    """Sets `edge_distance_m` and `side` on every target: how close the base can stand to that target, with
    the meaning of the task's free_floor row (floor projection to the edge of the nearest free disc connected
    to the dock). The anchor's own number is not enough on a deep surface: the far end of a stroke across a
    0.6 m counter is farther from any floor than the counter's centre is. Targets with the same floor
    projection share one measurement; one at the anchor's own point reuses the pre-pass value."""
    seen = {}
    if at_anchor.get("edge_distance_m") is not None:
        seen[(round(float(anchor["point"][0]), 4), round(float(anchor["point"][1]), 4))] = at_anchor
    for t in targets:
        key = (round(float(t["point"][0]), 4), round(float(t["point"][1]), 4))
        if key not in seen:
            seen[key] = nav.free_floor_at(world, anchor["id"], key, radius_m=radius_m)
        if seen[key].get("edge_distance_m") is not None:
            t["edge_distance_m"] = seen[key]["edge_distance_m"]
            t["side"] = [float(v) for v in seen[key]["side"]]


def _demo_check(re: dict, targets: list) -> dict:
    """Sanity check of generated targets against the re-anchored demo: the hand must move into the
    fixture (approach direction along the tool axis), and its work-phase poses must be near a target."""
    axis = np.asarray(targets[0]["tool_axis"], dtype=float)
    along = float(np.dot(re["approach_direction"], axis)) if re["approach_direction"] else None
    pts = np.asarray([t["point"] for t in targets], dtype=float)
    work = [np.asarray(s["p"], dtype=float) for s in re["path"] if s["phase"] == "work"]
    off = max((float(np.min(np.linalg.norm(pts - w, axis=1))) for w in work), default=None)
    ok = (along is None or along > 0.0) and (off is None or off <= DEMO_NEAR_M)
    return {"ok": bool(ok), "approach_along_tool_axis": None if along is None else round(along, 3),
            "work_pose_max_offset_m": None if off is None else round(off, 3), "work_poses": len(work)}


# ------------------------------------------------------------------------------- the ledger

def _building_rows(world: dict, building: dict) -> list:
    d = building["demands"]
    doors = {x["id"]: x for x in world.get("doorways", [])}
    rows = []
    if d.get("narrowest_m") is not None:
        door = d.get("narrowest_doorway")
        src = (doors.get(door) or {}).get("source")
        rows.append(_row("r_width", None, "base_width_max", round(d["narrowest_m"] - 2 * SIDE_MARGIN_M, 3), "m", 0.0,
                         "scan:mesh" if src == "mesh" else "scan",
                         **{"from": f"{door or 'hallway'} {d['narrowest_m']} m less {SIDE_MARGIN_M} m a side"}))
    if d.get("tightest_turn_m") is not None:
        rows.append(_row("r_length", None, "base_length_max", round(d["tightest_turn_m"] - 2 * SIDE_MARGIN_M, 3), "m", 0.0,
                         "scan", **{"from": f"hallway {d['tightest_turn_m']} m wide at the tightest turn into a doorway, "
                                            f"less {SIDE_MARGIN_M} m at each end"}))
    if d.get("lowest_header_m") is not None:
        rows.append(_row("r_header", None, "stowed_height_max", round(d["lowest_header_m"] - HEADER_MARGIN_M, 3), "m", 0.0,
                         "scan", **{"from": f"lowest header {d['lowest_header_m']} m less {HEADER_MARGIN_M} m"}))
    step = float(d.get("tallest_step_m") or 0.0)
    measured = world.get("mesh") is not None
    rows.append(_row("r_step", None, "step_max", step, "m", 0.0, "scan" if measured else "assumed",
                     **{"from": "tallest step on any corridor" if measured else
                        f"doorway records give {step} m; steps are not measured from a mesh, corridor assumed flat"}))
    return rows


def _force_band(tid, card, mass, grip):
    """(row or None, conflict or None). Low end: the most of the demo's minimum and the physics minimum
    (pinch: hold the mass with friction 0.5 and a safety factor of 1.5; hook: zero). High end: the demo's peak."""
    f = grip.get("force_n") or {}
    hold = (card or {}).get("hold")
    physics = SAFETY * mass * G / (2 * FRICTION) if hold == "pinch" else 0.0
    low, high = max(float(f.get("min", 0.0)), physics), float(f.get("peak", f.get("max", 0.0)))
    src = grip.get("source")
    labels = ["demo:home"] + ([] if src == "glove" else ["uncalibrated"])
    note = (f"low = max(demo min {f.get('min')} N, physics min {round(physics, 2)} N for a {hold} hold of {mass} kg); "
            f"high = demo peak. The bulb's unscrew torque is not on its card, so it is not in the low end")
    if low > high:
        return None, {"kind": "empty_force_band", "task": tid, "requirement": f"r_{tid}_force", "low_n": round(low, 2),
                      "high_n": round(high, 2), "grip_source": src, "ask_user": src == "glove",
                      "note": "the physics minimum is above the demo's peak; " +
                              ("ask for the object's mass or a new squeeze demo" if src == "glove" else
                               "the band is uncalibrated trigger travel, so nobody is asked") +
                              ". No force_band row is written, so the design is not rejected on it"}
    return _row(f"r_{tid}_force", tid, "force_band", [round(low, 2), round(high, 2)], "N", 0.0, "demo:home",
                grip_source=src, labels=labels, **{"from": note}), None


def step(state: dict) -> dict:
    """Reads state["world"], ["tasks"], ["building"], and optional ["demos"] and ["grips"] ({task id: file dict}).
    Writes state["requirements"] (requirements.json)."""
    world, tasks, building = state["world"], state["tasks"], state["building"]
    demos, grips = state.get("demos") or {}, state.get("grips") or {}
    anchors = {a["id"]: a for a in world.get("anchors", [])}
    rows, conflicts = _building_rows(world, building), []
    for t in tasks:
        tid, skill = t["id"], t["skill"]
        anchor, card = anchors.get(t.get("anchor")), object_card(t.get("object") or "")
        demo, grip = demos.get(tid), grips.get(tid)
        if anchor is None:
            if skill != "navigate":
                conflicts.append({"kind": "missing_anchor", "task": tid, "ask_user": True,
                                  "note": f"anchor {t.get('anchor')!r} is not in the world; no per-task rows written"})
            continue
        if card is None and t.get("object"):
            conflicts.append({"kind": "missing_object_card", "task": tid, "ask_user": True,
                              "note": f"no card catalog/object/{t['object']}.json; payload, opening and roll rows left out"})

        # reach targets, in the world frame
        floor = building["free_floor"].get(tid) or {}
        if skill in ("twist_out", "twist_in"):
            targets = twist_targets(anchor, card)
        elif skill == "wipe":
            targets = wipe_targets(anchor, floor.get("side"))
        elif skill in ("pick", "place"):
            targets = pick_targets(anchor)
        else:
            targets = []
        if targets:
            radius = float(floor.get("radius_m") or building.get("radius_m") or 0.0)
            if radius > 0:
                _target_floors(world, anchor, targets, radius, floor)
            extra = {"anchor": anchor["id"], "yaw_free": fixture_frame(anchor)[2]}
            if skill == "wipe":
                extra["strokes"] = len(targets) // 2
                extra["from"] = (f"strokes regenerated over {anchor['id']}'s extent inset {WIPE_INSET_M} m, lanes "
                                 f"{WIPE_LANE_M} m apart; targets 2k and 2k+1 are the ends of stroke k")
            if demo:
                re = reanchor(demo, anchor)
                extra["approach_direction"] = re["approach_direction"]
                extra["demo_check"] = _demo_check(re, targets)
                extra["labels"] = ["hand-to-gripper transform not applied (gap G12)"]
                if not extra["demo_check"]["ok"]:
                    conflicts.append({"kind": "demo_disagrees_with_targets", "task": tid, "requirement": f"r_{tid}_reach",
                                      "ask_user": False, **extra["demo_check"]})
            rows.append(_row(f"r_{tid}_reach", tid, "reach_targets", targets, "pose", REACH_TOLERANCE_M,
                             "demo:home+scan" if demo else "assumed", **extra))

        # free floor near the anchor
        if floor.get("edge_distance_m") is None:
            conflicts.append({"kind": "no_free_floor", "task": tid, "ask_user": False,
                              "note": f"no floor connected to the dock fits a {building.get('radius_m')} m disc"})
        else:
            rows.append(_row(f"r_{tid}_floor", tid, "free_floor",
                             {"edge_distance_m": floor["edge_distance_m"], "side": floor["side"]}, "m",
                             FREE_FLOOR_TOLERANCE_M, "scan", disc_radius_m=floor.get("radius_m")))

        # the object: opening, payload, force band, wrist roll
        if card is not None:
            grasps = skill in ("twist_out", "twist_in", "pick", "place", "carry")
            two = (demo or {}).get("two_handed")
            if grasps and isinstance(two, dict) and isinstance(two.get("width_m"), (int, float)):
                rows.append(_row(f"r_{tid}_opening", tid, "gripper_opening_min", round(float(two["width_m"]), 3), "m", 0.0,
                                 "demo:home", **{"from": "the demo's two-hand width"}))
            elif grasps and card.get("width_m") is not None:
                rows.append(_row(f"r_{tid}_opening", tid, "gripper_opening_min",
                                 round(float(card["width_m"]) + OPENING_MARGIN_M, 3), "m", 0.0, "card",
                                 **{"from": f"{card['id']} width {card['width_m']} m plus {OPENING_MARGIN_M} m"}))
            stated = t.get("object_mass_kg")
            mass = float(stated if stated is not None else card["mass_kg"])
            rows.append(_row(f"r_{tid}_payload", tid, "payload", mass, "kg", 0.0, "user" if stated is not None else "card",
                             **{"from": f"tasks file states {mass} kg (card default {card['mass_kg']} kg)"
                                if stated is not None else f"{card['id']} card"}))
            if grip and grasps:
                row, conflict = _force_band(tid, card, mass, grip)
                if row:
                    rows.append(row)
                if conflict:
                    conflicts.append(conflict)
            if skill in ("twist_out", "twist_in") and card.get("turns_to_remove") is not None:
                rows.append(_row(f"r_{tid}_roll", tid, "wrist_roll_turns", float(card["turns_to_remove"]), "turn", 0.0, "card"))
        if skill == "wipe":
            stated = t.get("press_force_n")
            rows.append(_row(f"r_{tid}_press", tid, "press_force", float(stated if stated is not None else PRESS_DEFAULT_N),
                             "N", PRESS_TOLERANCE_N, "user" if stated is not None else "assumed"))

    requirements = {"schema": "requirements/1", "world": world.get("id"), "tasks": [dict(t) for t in tasks],
                    "corridors": building["corridors"], "requirements": rows, "conflicts": conflicts}
    return {**state, "requirements": requirements}
