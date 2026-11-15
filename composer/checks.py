"""The hard checks. Every number a check compares against comes from the requirements ledger; every number
about the robot comes from the part cards or the composed model.

Two groups:
  arithmetic(parts, ledger)  card numbers only, no model. Complete for steps, base payload, payload, opening,
                             force, press and the sensors that must be present. For doorway, turn, door
                             header and reach it gives only a bound ("the base alone is already too wide"),
                             which `design` uses to drop candidates before composing anything.
  measured(parts, ledger)    on the composed model: doorway, turn, door header, lidar view, reach, tip-over, twist.
`check` runs both and keeps the measured result wherever there is one.
"""
from __future__ import annotations

import numpy as np

from . import model as M
from . import parts as P

GRASP_SKILLS = {"twist_out", "twist_in", "pick", "carry", "place"}
# what a skill's task is expected to have in the ledger; a missing one is reported, not guessed
SKILL_CHECKS = {"twist_out": ["reach", "payload", "opening", "force", "twist"],
                "twist_in": ["reach", "payload", "opening", "force", "twist"],
                "wipe": ["reach", "press"],
                "pick": ["reach", "payload", "opening", "force"],
                "carry": ["payload"], "place": ["reach", "payload"], "navigate": []}
QUANTITY = {"reach": "reach_targets", "payload": "payload", "opening": "gripper_opening_min", "force": "force_band",
            "press": "press_force", "twist": "wrist_roll_turns"}
ORDER = ["doorway", "turn", "door header", "steps", "base payload", "lidar present", "lidar view", "wrist camera",
         "ego camera", "reach", "tip-over", "payload", "opening", "force", "press", "twist"]
STROKE_MARGIN_M = 0.10               # a stroke's far end must be this far inside the envelope: the envelope is sampled
                                     # without the furniture, and over a table the elbow needs room to stay above it
MOUNT_BELOW_M = 0.05                 # the arm's mount may be at most this far below a surface it wipes
SIDE_SIN = np.sin(np.radians(15.0))  # and as level ("side") within this of horizontal
AXIS_COS = np.cos(np.radians(30.0))  # a target's tool axis counts as up or down within this of vertical


class Ledger:
    def __init__(self, requirements: dict):
        self.tasks = requirements.get("tasks", [])
        self.rows_all = requirements.get("requirements", [])

    def rows(self, quantity, task=None):
        return [r for r in self.rows_all if r["quantity"] == quantity and r.get("task") == task]

    def number(self, quantity, task, pick):
        """(value, ids) for a scalar quantity; when it is listed twice, `pick` (min or max) takes the tighter."""
        rows = self.rows(quantity, task)
        if not rows:
            return None, []
        return float(pick(r["value"] for r in rows)), [r["id"] for r in rows]

    def heaviest(self):
        rows = [r for r in self.rows_all if r["quantity"] == "payload"]
        return (max(float(r["value"]) for r in rows), [r["id"] for r in rows]) if rows else (0.0, [])


def _res(check, task, status, value=None, limit=None, unit=None, reqs=(), why=None, bound=False):
    r = {"check": check, "task": task, "status": status}
    if value is not None:
        r["value"] = value
    if limit is not None:
        r["limit"] = limit
    if unit:
        r["unit"] = unit
    r["requirements"] = list(reqs)
    if why:
        r["why"] = why
    if bound:
        r["_bound"] = True
    return r


def _pf(ok):
    return "pass" if ok else "fail"


def _r(x, n=3):
    return round(float(x), n)


def _missing(check, task):
    return _res(check, task["id"], "not_assessable",
                why=f"no {QUANTITY[check]} requirement in the ledger for this {task['skill']} task")


def _grasps(L: Ledger):
    ids = [r["id"] for r in L.rows_all if r["quantity"] == "gripper_opening_min"]
    return bool(ids) or any(t["skill"] in GRASP_SKILLS for t in L.tasks), ids


# ----------------------------------------------------------------------------------- arithmetic


def arithmetic(parts: dict, L: Ledger) -> list:
    parts = P.full(parts)
    B = P.base_info(parts["base"])
    lift, arm, grip, lidar = (P.card(s, parts[s]) for s in ("lift", "arm", "gripper", "lidar"))
    cam = P.camera()
    o = B["outline_m"]
    base_w, base_l = o["y"][1] - o["y"][0], o["x"][1] - o["x"][0]
    out = []

    # bounds on what the composed model will measure
    v, ids = L.number("base_width_max", None, min)
    if v is not None and base_w > v:
        out.append(_res("doorway", None, "fail", _r(base_w), v, "m", ids, "the base alone is wider than the limit", bound=True))
    v, ids = L.number("base_length_max", None, min)
    if v is not None and not B["holonomic"] and base_l > v:
        out.append(_res("turn", None, "fail", _r(base_l), v, "m", ids,
                        "the base alone is longer than the limit and cannot move sideways", bound=True))
    v, ids = L.number("stowed_height_max", None, min)
    low = o["z"][1] + lift["retracted_m"]
    if v is not None and low > v:
        out.append(_res("door header", None, "fail", _r(low), v, "m", ids, "the base and retracted lift alone are taller than the limit", bound=True))
    z_max = o["z"][1] + lift["retracted_m"] + lift["stroke_m"] + P.arm_span(parts["arm"], parts["gripper"])
    for t in L.tasks:
        for r in L.rows("reach_targets", t["id"]):
            top = max(float(g["point"][2]) for g in r["value"])
            if top > z_max:
                out.append(_res("reach", t["id"], "fail", _r(z_max), _r(top), "m", [r["id"]],
                                f"a target at {top:.2f} m is above anything these parts reach ({z_max:.2f} m: base top, lift fully up, arm and gripper stretched straight up)", bound=True))

    # complete checks
    v, ids = L.number("step_max", None, max)
    if v is None:
        out.append(_res("steps", None, "not_assessable", why="no step_max requirement in the ledger"))
    else:
        out.append(_res("steps", None, _pf(B["step_max_m"] >= v), B["step_max_m"], v, "m", ids,
                        "value is the tallest step the base climbs; limit is the tallest step on the corridors"))
    heaviest, pids = L.heaviest()
    carried = P.part_mass(parts) - B["mass_kg"] + heaviest
    out.append(_res("base payload", None, _pf(B["payload_kg"] >= carried), _r(carried, 2), B["payload_kg"], "kg", pids,
                    "value is everything the base carries (lift, arm, gripper, sensors, heaviest object); limit is the base's rating"))
    need_3d = v is not None and v > 0.02
    if parts["lidar"] == "none":
        out.append(_res("lidar present", None, "fail", reqs=ids, why="the robot cannot localise or see obstacles without a lidar"))
    elif need_3d and lidar["dim"] != "3d":
        out.append(_res("lidar present", None, "fail", lidar["dim"], "3d", None, ids,
                        f"the corridors have a {v:.2f} m step; a 2D lidar cannot see it"))
    else:
        out.append(_res("lidar present", None, "pass", lidar["dim"], "3d" if need_3d else "2d", None, ids))
    grasps, gids = _grasps(L)
    if grasps:
        out.append(_res("wrist camera", None, _pf(parts["wrist_cam"]), reqs=gids,
                        why=f"a grasp needs a close view; the ego camera's depth stops working under {cam['range_m'][0]} m"))
    out.append(_res("ego camera", None, _pf(parts["ego_cam"] != "none"),
                    why="needed to see the floor ahead and each target before reaching"))

    wrist_kg = cam["mass_kg"] if parts["wrist_cam"] else 0.0
    for t in L.tasks:
        tid, expected = t["id"], SKILL_CHECKS.get(t["skill"], [])
        v, ids = L.number("payload", tid, max)
        if v is not None:
            arm_load = v + grip["mass_kg"] + wrist_kg
            ok = arm["payload_kg"] >= arm_load and grip["payload_kg"] >= v
            out.append(_res("payload", tid, _pf(ok), _r(arm_load, 3), arm["payload_kg"], "kg", ids,
                            f"arm carries object {v} + gripper {grip['mass_kg']} + wrist camera {wrist_kg} kg against its "
                            f"{arm['payload_kg']} kg rating; gripper rated {grip['payload_kg']} kg for the {v} kg object"))
        elif "payload" in expected:
            out.append(_missing("payload", t))
        v, ids = L.number("gripper_opening_min", tid, max)
        if v is not None:
            out.append(_res("opening", tid, _pf(grip["stroke_m"] >= v), grip["stroke_m"], v, "m", ids))
        elif "opening" in expected:
            out.append(_missing("opening", t))
        rows = L.rows("force_band", tid)
        if rows:
            ids = [r["id"] for r in rows]
            band = [max(float(r["value"][0]) for r in rows), min(float(r["value"][1]) for r in rows)]
            if not grip["force_control"]:
                out.append(_res("force", tid, "fail", grip["force_n"], band, "N", ids, "gripper only opens and closes; it cannot hold a set force"))
            elif any(r.get("grip_source") != "glove" for r in rows):
                out.append(_res("force", tid, "not_assessable", grip["force_n"], band, "N", ids,
                                "the band is uncalibrated trigger travel, not newtons (grip_source is not glove)"))
            else:
                ok = max(band[0], grip["force_n"][0]) <= min(band[1], grip["force_n"][1])
                out.append(_res("force", tid, _pf(ok), grip["force_n"], band, "N", ids,
                                "value is the range of force the gripper holds; it must overlap the band. Force resolution is not on the card, so it is not tested"))
        elif "force" in expected:
            out.append(_missing("force", t))
        rows = L.rows("press_force", tid)
        if rows:
            ids = [r["id"] for r in rows]
            need = max(float(r["value"]) + float(r.get("tolerance") or 0.0) for r in rows)
            can = _r(arm["payload_kg"] * M.G, 1)
            if any(r.get("source") == "assumed" for r in rows):
                out.append(_res("press", tid, "not_assessable", can, need, "N", ids, "press force is assumed"))
            else:
                out.append(_res("press", tid, _pf(can >= need), can, need, "N", ids,
                                "value is the arm's payload rating times g, taken as the force it can push with (assumed; no force sensing figure on the card)"))
        elif "press" in expected:
            out.append(_missing("press", t))
    return out


# ------------------------------------------------------------------------------------- measured


def _axis_name(a):
    a = np.asarray(a, dtype=float)
    z = a[2] / (np.linalg.norm(a) or 1.0)
    return "up" if z > AXIS_COS else "down" if z < -AXIS_COS else "side" if abs(z) < SIDE_SIN else None


def measured(parts: dict, L: Ledger) -> list:
    parts = P.full(parts)
    robot = M.robot(parts)
    B = robot.B
    o = B["outline_m"]
    inscribed = min(-o["x"][0], o["x"][1], -o["y"][0], o["y"][1])
    lift = P.card("lift", parts["lift"])
    out = []

    w_lim, w_ids = L.number("base_width_max", None, min)
    stow = robot.stow(w_lim or 0.0, L.number("stowed_height_max", None, min)[0] or 0.0)
    if w_lim is None:
        out.append(_res("doorway", None, "not_assessable", stow["width_m"], unit="m", why="no base_width_max requirement in the ledger"))
    else:
        out.append(_res("doorway", None, _pf(stow["width_m"] <= w_lim), stow["width_m"], w_lim, "m", w_ids,
                        "width of the whole robot with the arm stowed"))
    v, ids = L.number("base_length_max", None, min)
    if B["holonomic"]:
        out.append(_res("turn", None, "pass", stow["length_m"], v, "m", ids,
                        "holonomic base: it moves sideways, so it need not turn in the hallway"))
    elif v is None:
        out.append(_res("turn", None, "not_assessable", stow["length_m"], unit="m", why="no base_length_max requirement in the ledger"))
    else:
        out.append(_res("turn", None, _pf(stow["length_m"] <= v), stow["length_m"], v, "m", ids,
                        "length of the whole robot with the arm stowed; this base must turn to face a doorway"))
    v, ids = L.number("stowed_height_max", None, min)
    if v is None:
        out.append(_res("door header", None, "not_assessable", stow["height_m"], unit="m", why="no stowed_height_max requirement in the ledger"))
    else:
        out.append(_res("door header", None, _pf(stow["height_m"] <= v), stow["height_m"], v, "m", ids,
                        "height with the lift down and the arm stowed"))
    if parts["lidar"] != "none":
        clear = robot.lidar_clear()  # in the stowed pose, set by stow() above
        out.append(_res("lidar view", None, _pf(clear >= M.LIDAR_CLEAR), _r(clear, 2), M.LIDAR_CLEAR, "fraction", [],
                        f"share of the horizontal circle the lidar sees past the robot's own body, arm stowed, mount {parts['lidar_mount']}"))

    roll = robot.wrist_roll()
    for t in L.tasks:
        tid, expected = t["id"], SKILL_CHECKS.get(t["skill"], [])
        payload, pay_ids = L.number("payload", tid, max)
        press, press_ids = L.number("press_force", tid, max)
        payload, press = payload or 0.0, press or 0.0
        floor_rows = L.rows("free_floor", tid)
        task_edge = max((float(r["value"].get("edge_distance_m", 0.0)) for r in floor_rows), default=0.0)
        reach_rows = L.rows("reach_targets", tid)
        reach_ids = [r["id"] for r in reach_rows] + [r["id"] for r in floor_rows]
        targets = [g for r in reach_rows for g in r["value"]]

        # reach: each target against the envelope of the composed model, with the base no closer than the free
        # floor allows for THAT target (its own edge_distance_m; the task's free_floor row when it has none).
        # Every target must be reachable from some legal standoff; they need not share one. No inverse kinematics here.
        # A sampled pose must sit at or past the nearest legal distance: no slack, since pathing then has to
        # find that pose by inverse kinematics and a near miss here becomes a redesign there.
        poses, worst, per_target = [], None, []  # worst: (status rank, margin, result)
        for i, g in enumerate(targets):
            h, axis = float(g["point"][2]), _axis_name(g.get("tool_axis", [0, 0, -1]))
            own = g.get("edge_distance_m")
            edge = float(own) if own is not None else task_edge
            d_min = edge + inscribed if edge > 0 else 0.0
            floor = f"free floor {edge:.2f} m from {'this target' if own is not None else 'the anchor'} + half the base"
            if axis is None:
                per_target.append({"target": i, "status": "not_assessable", "needed_m": _r(d_min)})
                cand = (1, 0.0, _res("reach", tid, "not_assessable", reqs=reach_ids,
                                     why=f"target {i}: the envelope is tabulated only for the tool pointing up, down or level; standoff search (inverse kinematics) decides"))
            else:
                entries = robot.envelope_at(axis, h)
                usable = [e for e in (entries or []) if e[0] >= d_min]
                far = _r(entries[-1][0]) if entries else 0.0
                per_target.append({"target": i, "status": _pf(bool(usable)), "needed_m": _r(d_min), "reach_m": far})
                if not entries:
                    tops = [k[1] * M.ENV_STEP for k in robot.envelope() if k[0] == axis]
                    span = f"{min(tops):.2f} to {max(tops):.2f} m" if tops else "nowhere"
                    cand = (2, 0.0, _res("reach", tid, "fail", 0.0, _r(d_min), "m", reach_ids,
                                         f"target {i} at {h:.2f} m, tool {axis}: outside the envelope, which spans heights {span} with the tool {axis}"))
                elif not usable:
                    cand = (2, d_min - entries[-1][0], _res(
                        "reach", tid, "fail", far, _r(d_min), "m", reach_ids,
                        f"target {i} at {h:.2f} m, tool {axis}: the tool gets {entries[-1][0]:.2f} m from the base centre, "
                        f"but the base centre can stand no closer than {d_min:.2f} m to it ({floor})"))
                else:
                    poses.append((i, h, axis, g, usable[0]))
                    cand = (0, -(entries[-1][0] - d_min), _res(
                        "reach", tid, "pass", far, _r(d_min), "m", reach_ids,
                        f"target {i} at {h:.2f} m, tool {axis}: the tool reaches {entries[0][0]:.2f} to {entries[-1][0]:.2f} m from the base centre; "
                        f"the base centre can stand {d_min:.2f} m away or more ({floor}). value is the farthest reach at that height, limit the nearest the base can stand"))
            cand[2]["target"] = i
            if worst is None or cand[:2] > worst[:2]:
                worst = cand
        # a wipe stroke (targets 2k and 2k+1 of a row that says how many strokes it has) is done from one
        # parked pose, so both its ends must be in reach from the same place. Estimate: stand on the nearest
        # free floor to one end (its edge_distance_m along its `side`) and measure to the other end.
        at = 0
        for r in reach_rows:
            vals = r["value"]
            for k in range(int(r.get("strokes") or 0)):
                ga, gb = vals[2 * k], vals[2 * k + 1]
                axis = _axis_name(ga.get("tool_axis", [0, 0, -1]))
                entries = robot.envelope_at(axis, float(ga["point"][2])) if axis else None
                if not entries or any(g.get("edge_distance_m") is None or g.get("side") is None for g in (ga, gb)):
                    continue
                far = entries[-1][0]
                span = []
                for g, other in ((ga, gb), (gb, ga)):
                    stand = np.asarray(g["point"][:2], dtype=float) + np.asarray(g["side"], dtype=float) * (float(g["edge_distance_m"]) + inscribed)
                    span.append(float(np.linalg.norm(stand - np.asarray(other["point"][:2], dtype=float))))
                need = min(span)
                if need > far - STROKE_MARGIN_M:
                    length = float(np.linalg.norm(np.asarray(ga["point"][:2]) - np.asarray(gb["point"][:2])))
                    cand = (2, need - far, _res(
                        "reach", tid, "fail", _r(far), _r(need), "m", reach_ids,
                        f"stroke {k} ({length:.2f} m long, targets {at + 2 * k} and {at + 2 * k + 1}): one parked pose must reach both ends; from the "
                        f"nearest free floor to either end the other end is {need:.2f} m from the base centre, and the tool reaches {far:.2f} m at that height (less {STROKE_MARGIN_M} m of margin)"))
                    cand[2]["target"] = at + 2 * k + 1
                    if worst is None or cand[:2] > worst[:2]:
                        worst = cand
            at += len(vals)
            # wiping a surface from a mount well below it means draping the arm over the surface's edge
            if int(r.get("strokes") or 0) and vals:
                h = max(float(g["point"][2]) for g in vals)
                mount = o["z"][1] + (lift["retracted_m"] + lift["stroke_m"] if lift["stroke_m"] > 0 else 0.0)
                if _axis_name(vals[0].get("tool_axis", [0, 0, -1])) == "down" and mount < h - MOUNT_BELOW_M:
                    cand = (2, h - mount, _res(
                        "reach", tid, "fail", _r(mount), _r(h - MOUNT_BELOW_M), "m", reach_ids,
                        f"the arm's mount gets no higher than {mount:.2f} m and the surface to wipe is at {h:.2f} m: "
                        f"from below, the elbow and forearm have to cross the surface's edge to reach onto it"))
                    cand[2]["target"] = 0
                    if worst is None or cand[:2] > worst[:2]:
                        worst = cand
        if worst is not None:
            if len(targets) > 1:
                bad = [p["target"] for p in per_target if p["status"] == "fail"]
                worst[2]["why"] += (f" (the worst of {len(targets)} targets; {len(bad)} out of reach: {bad})" if bad else
                                    f" (the tightest of {len(targets)} targets)")
            worst[2]["targets"] = per_target
            out.append(worst[2])
        elif "reach" in expected:
            out.append(_missing("reach", t))

        # tip-over: static, at the envelope pose for each target, and stowed when carrying or with no target
        cases = []
        for i, h, axis, g, (dist, named) in poses:
            robot.set(robot.vec(named))
            a = np.asarray(g.get("tool_axis", [0, 0, -1]), dtype=float)
            a /= np.linalg.norm(a)
            cases.append((robot.tip_sf(payload, -press * a), f"reaching target {i} ({dist:.2f} m out at {h:.2f} m, the nearest the base can stand to it)"))
        if t.get("carries") or not poses:
            robot.set(robot.vec(stow["arm"]))
            cases.append((robot.tip_sf(payload), "stowed, carrying" if payload else "stowed"))
        ratio, where = min(cases, key=lambda c: c[0])
        note = f"worst case: {where}; payload {payload} kg, press {press} N; static, against the support polygon"
        if press and not poses:
            note += "; the press force is not applied because the task has no reach target to place it at"
        out.append(_res("tip-over", tid, _pf(ratio >= M.TIP_SF), _r(min(ratio, 99.0), 2), M.TIP_SF, "ratio",
                        pay_ids + press_ids + reach_ids, note))

        # twist
        v, ids = L.number("wrist_roll_turns", tid, max)
        if v is not None:
            turns = roll["turns"]
            shown = None if np.isinf(turns) else _r(turns, 2)
            if not roll["along_tool"]:
                out.append(_res("twist", tid, "fail", 0.0, v, "turn", ids, f"the last joint ({roll['joint']}) does not turn about the tool's axis"))
            elif turns >= v:
                out.append(_res("twist", tid, "pass", shown, v, "turn", ids, f"{roll['joint']} rolls that far in one go"))
            else:
                n = int(np.ceil(v / turns))
                out.append(_res("twist", tid, "pass", shown, v, "turn", ids,
                                f"{roll['joint']} rolls {turns:.2f} turns; needs {n} grasps (regrasp {n - 1} time{'s' if n > 2 else ''}), which pathing must plan"))
        elif "twist" in expected:
            out.append(_missing("twist", t))
    return out


# ---------------------------------------------------------------------------------------- check


def _sorted(results):
    return sorted(results, key=lambda r: (ORDER.index(r["check"]), r["task"] or ""))


def labels(results) -> list:
    by = {}
    for r in results:
        if r["status"] == "not_assessable":
            by.setdefault(r["check"], []).append(r["task"] or "building")
    return [f"{c} not verified: {', '.join(ts)}" for c, ts in by.items()]


def cheap_failures(parts: dict, L: Ledger) -> list:
    return [r for r in arithmetic(parts, L) if r["status"] == "fail"]


def check(parts: dict, requirements: dict) -> dict:
    parts = P.full(parts)
    P.validate(parts)
    L = Ledger(requirements)
    results = _sorted([r for r in arithmetic(parts, L) if not r.get("_bound")] + measured(parts, L))
    return {"parts": parts, "feasible": all(r["status"] != "fail" for r in results), "price_usd": P.price(parts),
            "mass_kg": round(M.robot(parts).mass, 2), "checks": results, "labels": labels(results)}
