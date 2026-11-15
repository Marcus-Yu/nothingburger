"""Step 5, pathing with a robot: standoffs (nav proposes, motion checks reach, the agent picks), then the
base route, then the arm path per task per standoff. Failures are recorded in the outputs, never raised."""
from __future__ import annotations

import copy
import math

from .. import observe
from ..tools import motion, nav
from ..tools import viz

MAX_TRIES = 8          # motion.reachable calls per task on the top proposals
SPARES = 2
MORE_TRIES = 8         # further proposals tried when the arm path fails from the picked pose and every spare
PROPOSALS = 36         # asked of nav.propose; the envelope filter then orders them
ENVELOPE_MARGIN_M = 0.025
COVER_TRIES = 240      # further motion.reachable calls spent on covering a wipe (each on one stroke's two ends)
COVER_PER_STROKE = 3   # poses tried for one uncovered stroke before it is given up


def _rows(requirements, tid, quantity):
    return [r for r in requirements["requirements"] if r.get("task") == tid and r["quantity"] == quantity]


def _number(requirements, tid, quantity):
    rows = _rows(requirements, tid, quantity)
    return float(rows[0]["value"]) if rows else 0.0


def _loads(task, requirements):
    """(payload_kg, tool_force_z_n) for motion.reachable. A wipe presses down, so the surface pushes the tool up."""
    press = _number(requirements, task["id"], "press_force") if task["skill"] == "wipe" else 0.0
    return _number(requirements, task["id"], "payload"), press


def _standoff(task, pose, res, spares, covers=None, n_targets=0):
    s = {"task": task["id"], "pose": [float(v) for v in pose], "task_yaw_rad": 0.0, "reach_ok": bool(res["ok"]),
         "tip_ratio": res["tip_ratio"], "spares": [[float(v) for v in p] for p in spares], "q": res.get("q", {}),
         "why": res.get("why", "")}
    if covers is not None:
        strokes = sorted({i // 2 for i in covers})
        s["covers_targets"] = list(covers)
        s["covers"] = "strokes " + _ranges(strokes) + f" of {n_targets // 2}"
    return s


def _ranges(nums):
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ", ".join(out)


def _envelope_ok(build: dict, pose, targets) -> bool:
    """The cheap geometric filter before IK: is every target, at its height, between the nearest and the
    farthest the tool gets from the base centre (build.json's reach envelope)? True when the table has no
    row for a target (tool not vertical, or no such height), so nothing is dropped on missing data."""
    rows = build.get("reach_envelope") or []
    for t in targets:
        az = float((t.get("tool_axis") or [0, 0, -1])[2])
        name = "up" if az > 0.87 else "down" if az < -0.87 else None
        mine = [r for r in rows if r.get("tool_axis", name) == name and abs(float(r["height_m"]) - float(t["point"][2])) <= 0.05]
        if name is None or not mine:
            continue
        row = min(mine, key=lambda r: abs(float(r["height_m"]) - float(t["point"][2])))
        d = math.hypot(float(t["point"][0]) - pose[0], float(t["point"][1]) - pose[1])
        if not (float(row["min_distance_m"]) + ENVELOPE_MARGIN_M <= d <= float(row["max_distance_m"]) - ENVELOPE_MARGIN_M):
            return False
    return True


def _propose_at(state, task, point, limit):
    """nav.propose around `point` instead of the anchor's own point (nav rings the anchor only, so a long
    surface gets poses near its middle and none near its ends): a copy of the world with the task's anchor
    moved there. The copy goes to nav only; nothing is written back."""
    return nav.propose(nav.moved(state["world"], task["anchor"], point), state["build"], task,
                       requirements=state["requirements"], limit=limit)


def _cover(state, task, targets, loads):
    """Greedy cover of a wipe's strokes (targets 2k, 2k+1) by several standoffs, in order along the surface:
    for the first uncovered stroke, propose poses around its middle, check its two ends at the nearest few,
    and at each pose that reaches them see how long a run of the following strokes it also reaches; keep the
    longest run whose arm path can be built, repeat. Returns (standoffs, uncovered stroke indices, notes)."""
    build, xml = state["build"], state["robot_xml"]
    payload, press = loads
    n_strokes = len(targets) // 2
    uncovered, given_up, chosen, notes, calls = list(range(n_strokes)), [], [], [], 0
    while uncovered and calls < COVER_TRIES:
        k = uncovered[0]
        ends = [targets[2 * k], targets[2 * k + 1]]
        mid = [(ends[0]["point"][i] + ends[1]["point"][i]) / 2 for i in (0, 1)]
        best, first_why, passing = None, None, []
        for pose in _propose_at(state, task, mid, 12)[:COVER_PER_STROKE]:
            if calls >= COVER_TRIES:
                break
            calls += 1
            res = motion.reachable(xml, pose, ends, build=build, payload_kg=payload, tool_force_z_n=press, obstacles=state["world"].get("obstacles"))
            if not res["ok"]:
                if first_why is None:  # keep the reason from the nearest pose
                    first_why = "; ".join(f"target {2 * k + i}: {w.split(': ', 1)[-1]}" if w.startswith("target ") else w
                                          for w in res["why"].split("; ")
                                          for i in [int(w[7]) if w.startswith("target ") and w[7].isdigit() else 0])
                continue
            run = [k]  # the unbroken run of uncovered strokes from k that this pose also reaches
            while k + len(run) in uncovered:
                nxt = k + len(run)
                more = motion.reachable(xml, pose, [targets[2 * nxt], targets[2 * nxt + 1]], build=build,
                                        payload_kg=payload, tool_force_z_n=press, obstacles=state["world"].get("obstacles"))
                calls += 1
                if not more["ok"]:
                    break
                run.append(nxt)
            idx = [i for s in run for i in (2 * s, 2 * s + 1)]
            res = motion.reachable(xml, pose, [targets[i] for i in idx], build=build, payload_kg=payload, tool_force_z_n=press, obstacles=state["world"].get("obstacles"))
            if res["ok"]:
                passing.append((pose, run, idx, res))
        # the longest run first; among the poses that reach, take the first whose arm path can actually be built
        passing.sort(key=lambda c: (-len(c[1]), -c[3]["tip_ratio"]))
        for cand in passing:
            trial = _retarget(state, task, _standoff(task, cand[0], cand[3], [], covers=cand[2], n_targets=len(targets)))
            if not trial.get("failure"):
                best = cand
                break
        if best is None and passing:
            best = passing[0]  # none builds: keep the best reach and let the arm-path step report why
        if best is None:
            given_up.append(k)
            uncovered.remove(k)
            notes.append(f"stroke {k}: {first_why or 'nav.propose returned no pose near it'}")
            continue
        pose, run, idx, res = best
        chosen.append(_standoff(task, pose, res, [], covers=idx, n_targets=len(targets)))
        uncovered = [s for s in uncovered if s not in run]
    if uncovered:
        notes.append(f"strokes {_ranges(uncovered)}: not tried, the cap of {COVER_TRIES} reach checks was spent")
    return chosen, sorted(given_up + uncovered), notes


def pick_standoffs(state: dict, task: dict) -> tuple[list, list]:
    """(standoffs for the task, failures). 5a: propose, check reach on the top proposals, pick by tip ratio."""
    world, build, xml, requirements = state["world"], state["build"], state["robot_xml"], state["requirements"]
    tid = task["id"]
    targets = [g for r in _rows(requirements, tid, "reach_targets") for g in r["value"]]
    if not targets:
        return [], ([] if task["skill"] == "navigate" else
                    [{"task": tid, "kind": "standoff", "reason": "no reach_targets requirement in the ledger"}])
    loads = _loads(task, requirements)
    proposals = nav.propose(world, build, task, requirements=requirements, limit=PROPOSALS)
    if not proposals:
        return [], [{"task": tid, "kind": "standoff", "reason": "nav.propose returned no collision-free pose connected to the dock"}]
    # nav's order, but poses the reach envelope rules out go last, so the IK tries are not spent on them
    ordered = sorted(proposals, key=lambda p: not _envelope_ok(build, p, targets))
    tried = {}
    for pose in ordered[:MAX_TRIES]:
        tried[tuple(pose)] = motion.reachable(xml, pose, targets, build=build, payload_kg=loads[0], tool_force_z_n=loads[1], obstacles=state["world"].get("obstacles"))
    passing = sorted((p for p, r in tried.items() if r["ok"]), key=lambda p: -tried[p]["tip_ratio"])
    if passing:
        best = passing[0]
        covers = list(range(len(targets))) if task["skill"] == "wipe" else None
        return [_standoff(task, best, tried[best], passing[1:1 + SPARES], covers=covers, n_targets=len(targets))], []
    if task["skill"] == "wipe" and len(targets) >= 4:
        chosen, uncovered, notes = _cover(state, task, targets, loads)
        fails = []
        if uncovered:
            idx = [i for s in uncovered for i in (2 * s, 2 * s + 1)]
            fails.append({"task": tid, "kind": "standoff", "reason": f"strokes {_ranges(uncovered)} of {len(targets) // 2} "
                          f"are not covered by any standoff", "uncovered_targets": idx, "notes": notes})
        return chosen, fails
    return [], [{"task": tid, "kind": "standoff", "reason": f"none of the top {len(tried)} proposals passes reach and tip-over",
                 "tried": [{"pose": list(p), "why": r["why"]} for p, r in tried.items()]}]


def _only_targets(requirements: dict, tid: str, indices) -> dict:
    """The ledger with the task's reach_targets cut to `indices` (motion.retarget reads every target of the task)."""
    out = dict(requirements)
    out["requirements"] = []
    for r in requirements["requirements"]:
        if r.get("task") == tid and r["quantity"] == "reach_targets":
            r = copy.copy(r)
            r["value"] = [r["value"][i] for i in indices]
        out["requirements"].append(r)
    return out


def _retarget(state, task, standoff):
    requirements = state["requirements"]
    ledger = requirements if "covers_targets" not in standoff else _only_targets(requirements, task["id"], standoff["covers_targets"])
    try:
        entry = motion.retarget((state.get("demos") or {}).get(task["id"]), state["robot_xml"], build=state["build"],
                                task=task, standoff=standoff, requirements=ledger, obstacles=state["world"].get("obstacles"))
    except Exception as e:
        entry = {"task": task["id"], "standoff": standoff["pose"], "segments": [],
                 "failure": {"segment": "approach", "why": f"motion.retarget raised {type(e).__name__}: {e}"}}
    if "covers" in standoff:
        entry["covers"], entry["covers_targets"] = standoff["covers"], standoff["covers_targets"]
    return entry


def _further(state, task, s):
    """Program fix, second part: the picked pose and its spares all reach the targets (motion.reachable) but no
    arm path can be built from them (typically the move out of the stowed pose hits the robot when the base
    stands very close). Go on down nav's proposals past the ones already used, up to MORE_TRIES poses that
    pass reach. Returns (pose, reach result, trajectory entry) or None."""
    requirements, build = state["requirements"], state["build"]
    targets = [g for r in _rows(requirements, task["id"], "reach_targets") for g in r["value"]]
    if len(s.get("covers_targets") or targets) != len(targets):
        return None  # one of several standoffs covering a wipe: its poses were proposed around its own strokes
    used = {tuple(float(v) for v in s["pose"])} | {tuple(float(v) for v in r["pose"]) for r in s.get("rejected", [])}
    payload, press = _loads(task, requirements)
    try:
        proposals = nav.propose(state["world"], build, task, requirements=requirements, limit=PROPOSALS)
    except Exception:  # nav raised: there is nothing further to try, and the failure already recorded stands
        return None
    ordered = sorted(proposals, key=lambda p: not _envelope_ok(build, p, targets))
    tries = 0
    for pose in ordered:
        if tuple(float(v) for v in pose) in used:
            continue
        if tries >= MORE_TRIES:
            break
        check = motion.reachable(state["robot_xml"], pose, targets, build=build, payload_kg=payload, tool_force_z_n=press, obstacles=state["world"].get("obstacles"))
        if not check["ok"]:
            continue
        tries += 1
        again = _retarget(state, task, dict(s, pose=pose))
        if not again.get("failure"):
            return pose, check, again
        s.setdefault("rejected", []).append({"pose": [float(v) for v in pose], "why": again["failure"]["why"]})
    return None


def _plan(state, standoffs):
    world = state["world"]
    try:
        return nav.plan(world, state["build"], requirements=state["requirements"], standoffs=standoffs)
    except Exception as e:
        return {"schema": "route/1", "world": world.get("id"), "standoffs": standoffs, "legs": [], "door_clearances": [],
                "failures": [{"kind": "route", "reason": f"nav.plan raised {type(e).__name__}: {e}"}]}


def step(state: dict) -> dict:
    """Reads state["world"], ["requirements"], ["build"], ["robot_xml"], optional ["demos"].
    Writes state["route"] (route.json) and state["trajectory"] (trajectory.json)."""
    requirements, build = state["requirements"], state["build"]
    standoffs, standoff_failures = [], []
    for task in requirements["tasks"]:
        try:
            chosen, fails = pick_standoffs(state, task)
        except Exception as e:  # a module raised: record it against the task and go on
            chosen, fails = [], [{"task": task["id"], "kind": "standoff", "reason": f"{type(e).__name__}: {e}"}]
        standoffs += chosen
        standoff_failures += fails
        for s in chosen:
            observe.emit("standoff", task=task["id"], skill=task["skill"], anchor=task["anchor"], pose=s["pose"], tip_ratio=s.get("tip_ratio"),
                         covers=s.get("covers"), why=s.get("why"),
                         frame=viz.render(state["robot_xml"], {**((build.get("stowed") or {}).get("qpos") or {}), **(s.get("q") or {})},
                                          f"reach-{task['id']}", pose=s["pose"]),
                         top=viz.robot_top(state["world"], state["robot_xml"],
                                           {**((build.get("stowed") or {}).get("qpos") or {}), **(s.get("q") or {})}, s["pose"], f"reach-{task['id']}"))
        for f in fails:
            observe.emit("standoff_failed", task=task["id"], skill=task["skill"], reason=f.get("reason"), notes=f.get("notes", [])[:4])

    route = _plan(state, standoffs)
    observe.emit("route", legs=[{k: leg.get(k) for k in ("from", "to", "carrying", "length_m", "waypoints")} for leg in route["legs"]],
                 door_clearances=route.get("door_clearances", []))

    tasks = {t["id"]: t for t in requirements["tasks"]}
    entries, failures, swapped = [], [], False
    for s in standoffs:
        task = tasks[s["task"]]
        entry = _retarget(state, task, s)
        # program fix: an arm path that cannot be built from the picked pose is tried from each spare
        while entry.get("failure") and s["spares"]:
            spare = s["spares"].pop(0)
            check = motion.reachable(state["robot_xml"], spare, [g for r in _rows(requirements, task["id"], "reach_targets")
                                                                 for g in r["value"]], build=build,
                                     payload_kg=_loads(task, requirements)[0], tool_force_z_n=_loads(task, requirements)[1])
            again = _retarget(state, task, dict(s, pose=spare))
            if not again.get("failure"):
                s.setdefault("rejected", []).append({"pose": s["pose"], "why": entry["failure"]["why"]})
                s.update(pose=[float(v) for v in spare], reach_ok=bool(check["ok"]), tip_ratio=check["tip_ratio"],
                         q=check.get("q", {}), why=check.get("why", ""))
                entry, swapped = again, True
            else:
                s.setdefault("rejected", []).append({"pose": [float(v) for v in spare], "why": again["failure"]["why"]})
        if entry.get("failure"):
            found = _further(state, task, s)
            if found:
                pose, check, again = found
                s.setdefault("rejected", []).append({"pose": s["pose"], "why": entry["failure"]["why"]})
                s.update(pose=[float(v) for v in pose], reach_ok=True, tip_ratio=check["tip_ratio"], q=check.get("q", {}),
                         why=check.get("why", ""))
                entry, swapped = again, True
        entries.append(entry)
        observe.emit("arm_path", task=task["id"], skill=task["skill"], pose=s["pose"], ok=not entry.get("failure"),
                     why=(entry.get("failure") or {}).get("why"), rejected=len(s.get("rejected", [])),
                     segments=[{"phase": g["phase"], "kind": g["kind"], "samples": len(g["samples"]),
                                "seconds": round(g["samples"][-1]["t"] - g["samples"][0]["t"], 1) if g["samples"] else 0}
                               for g in entry.get("segments", [])])
        if entry.get("failure"):
            failures.append({"task": task["id"], "kind": "arm path", "standoff": s["pose"], **entry["failure"]})
    if swapped:  # the route was planned to the first picks
        route = _plan(state, standoffs)
        observe.emit("route", replanned=True, door_clearances=route.get("door_clearances", []),
                     legs=[{k: leg.get(k) for k in ("from", "to", "carrying", "length_m", "waypoints")} for leg in route["legs"]])
    route["failures"] = list(route.get("failures", [])) + standoff_failures
    failures = [{**f, "why": f["reason"]} for f in standoff_failures] + failures
    trajectory = {"schema": "trajectory/1", "robot": "robot.xml", "joints": list(build["arm_joints"]), "tasks": entries,
                  "failures": failures}
    return {**state, "route": route, "trajectory": trajectory}
