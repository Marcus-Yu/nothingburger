"""Arm trajectories for one task at one standoff: approach, work, retreat, in joint space.

Near the work the tool moves on straight lines in the world, sampled every DT at SPEED with one
warm-started IK solve per sample. Between the stowed pose and the pre-approach point the arm moves
in joint space instead (a straight tool line from a folded arm tends to pass through the robot);
those samples get the same joint-limit and collision checks. Nothing here raises for a path that
cannot be built: the entry comes back with a `failure` naming the segment and the reason.
"""
from __future__ import annotations

import math

import mujoco
import numpy as np

from .ik import AXIS_TOL_DEG, POS_TOL, RESTARTS, Arm, unit

DT = 0.05  # s between samples: 20 a second
WIPE_SHORT_M = 0.06  # a wipe stroke may stop this far before its end when the arm runs out of reach there (recorded as short_m)
RAISE_M = 0.25  # the unfold goes by a point this far above the pre-approach when the direct move is blocked
SPEED = 0.1  # m/s, tool speed on a line
PRE_APPROACH = 0.10  # m back along the tool axis
PICK_LIFT = 0.15  # m straight up after closing on a pick
JOINT_SPEED = 1.0  # rad/s ceiling in transit (assumed; no part card gives joint speeds yet); the tool also keeps to SPEED
LIFT_SPEED = 0.1  # m/s for a prismatic joint in transit (assumed)
ROLL_SPEED = 1.5  # rad/s for the twisting joint (assumed)
DWELL = 0.5  # s held still while the gripper closes or opens (assumed)
JUMP_MAX = 0.5  # rad between neighbouring samples on a line: more means the IK changed branch
# Starting guesses for the grasp pose tried before giving up: the stowed pose, mid-range, then RESTARTS seeded
# random draws. This is exactly what ik.reachable tries for its first target (same order, same seed), so a pose
# that `reachable` accepts never fails here with "first target: out of reach".
CANDIDATES = 2 + RESTARTS
LINE_ITERS = 60


class _Fail(Exception):
    pass


class _Builder:
    def __init__(self, arm: Arm, pos_tol: float):
        self.arm = arm
        self.pos_tol = pos_tol
        self.t = 0.0
        self.q = arm.q_stowed.copy()
        self.segments: list[dict] = []
        self.max_err = 0.0
        self.collisions = 0
        self.phase, self.failure = "approach", None
        self.slide = np.array([arm.m.jnt_type[arm.m.joint(n).id] == mujoco.mjtJoint.mjJNT_SLIDE for n in arm.names])

    # ---- segments and samples

    def begin(self, phase: str, kind: str, **extra) -> dict:
        seg = {"phase": phase, "kind": kind, **extra, "events": [], "samples": []}
        self.segments.append(seg)
        self._sample(seg)
        return seg

    def _sample(self, seg: dict) -> None:
        q = np.round(self.q, 5)
        q = np.where(q > self.arm.hi, np.floor(self.arm.hi * 1e5) / 1e5, q)  # rounding must not step over a limit
        q = np.where(q < self.arm.lo, np.ceil(self.arm.lo * 1e5) / 1e5, q)
        seg["samples"].append({"t": round(self.t, 3), "q": [float(v) for v in q]})

    def emit(self, seg: dict, qs) -> None:
        for q in qs:
            self.t += DT
            self.q = np.asarray(q, dtype=float).copy()
            self._sample(seg)

    def event(self, seg: dict, gripper: str) -> None:
        seg["events"].append({"t": round(self.t, 3), "gripper": gripper})

    def dwell(self, seg: dict, gripper: str) -> None:
        self.event(seg, gripper)
        self.emit(seg, [self.q] * round(DWELL / DT))

    # ---- motion pieces: each returns joint vectors, one per DT, and counts what it checked

    def check(self, q) -> None:
        """Joint limits and the self-collision test for one sample."""
        if not self.arm.within(q):
            raise _Fail("a sample leaves the joint limits")
        self.arm.set(q)
        if self.arm.collides():
            self.collisions += 1

    def transit(self, q_from, q_to) -> list[np.ndarray]:
        """Joint-space move. Raises if any sample collides."""
        q_from, q_to = np.asarray(q_from, dtype=float), np.asarray(q_to, dtype=float)
        rate = np.where(self.slide, LIFT_SPEED, JOINT_SPEED)
        n = max(1, math.ceil(float(np.max(np.abs(q_to - q_from) / rate)) / DT))
        path = lambda n: [q_from + (q_to - q_from) * k / n for k in range(n + 1)]
        tool = []
        for q in path(n):  # stretch the move until the tool, too, keeps to SPEED
            self.arm.set(q)
            tool.append(self.arm.tool_pos())
        step = float(np.max(np.linalg.norm(np.diff(tool, axis=0), axis=1)))
        n = max(n, math.ceil(n * step / (SPEED * DT)))
        before = self.collisions
        qs = path(n)[1:]
        for q in qs:
            self.check(q)
        if self.collisions > before:
            hit = self.collisions - before
            self.collisions = before
            raise _Fail(f"the joint-space move puts the arm into the base, lift, floor or furniture at {hit} of {n} samples")
        return qs

    def line(self, q_from, p0, p1, a0, a1, *, locked=None, steps: int | None = None, short_ok: float = 0.0) -> list[np.ndarray]:
        """Tool on the straight line p0 -> p1, tool axis turning a0 -> a1 (None: axis free). With `short_ok`
        (metres), a line the arm cannot finish may stop up to that far before p1; `self.short` then holds how
        far short it stopped."""
        self.short = 0.0
        p0, p1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        n = steps or max(1, math.ceil(float(np.linalg.norm(p1 - p0)) / (SPEED * DT)))
        q, qs = np.asarray(q_from, dtype=float), []
        before = self.collisions
        for k in range(1, n + 1):
            s = k / n
            axis = None if a0 is None else unit((1 - s) * a0 + s * a1)
            q_new, pe, ae = self.arm.solve(p0 + (p1 - p0) * s, axis, q, iters=LINE_ITERS, locked=locked)
            if pe > self.pos_tol or ae > AXIS_TOL_DEG:
                left = float(np.linalg.norm(p1 - p0)) * (n - k + 1) / n
                if qs and left <= short_ok:
                    self.short = left
                    break
                raise _Fail(f"IK lost the path at sample {k} of {n}: {pe * 1000:.0f} mm, {ae:.0f} deg off")
            if float(np.max(np.abs(q_new - q)[~self.slide], initial=0.0)) > JUMP_MAX:
                raise _Fail(f"IK changed branch at sample {k} of {n}")
            self.max_err = max(self.max_err, pe)
            self.check(q_new)
            q = q_new
            qs.append(q)
        if self.collisions > before:
            raise _Fail(f"the arm is in the base, lift, floor or furniture at {self.collisions - before} of {n} samples")
        return qs


def _task_inputs(demo, task, requirements):
    reqs = requirements["requirements"] if isinstance(requirements, dict) else list(requirements)
    mine = [r for r in reqs if r.get("task") == task["id"]]
    by = {}
    for r in mine:
        by.setdefault(r["quantity"], []).append(r)
    targets, pos_tol = [], POS_TOL
    for r in by.get("reach_targets", []):
        targets += [dict(t) for t in r["value"]]
        if r.get("tolerance"):
            pos_tol = min(pos_tol, float(r["tolerance"]))
    for t in targets:
        t.setdefault("held_axes", ["position", "tool_axis"])
        if not t.get("tool_axis") and demo and demo.get("approach_direction"):
            # the demo's frame has z out of the anchor's surface; with no fixture normal passed in,
            # that z is taken as the world's up and the demo's heading about it as the world's
            t["tool_axis"] = [float(v) for v in unit(demo["approach_direction"])]
            t["held_axes"] = sorted(set(t["held_axes"]) | {"tool_axis"})
    one = lambda name: by[name][0]["value"] if name in by else None
    return targets, pos_tol, one("wrist_roll_turns"), one("press_force")


def _axis(target):
    return unit(target["tool_axis"]) if "tool_axis" in target["held_axes"] and target.get("tool_axis") else None


def retarget(demo, robot: str, *, build: dict, task: dict, standoff, requirements, obstacles=None) -> dict:
    pose = [float(v) for v in (standoff["pose"] if isinstance(standoff, dict) else standoff)]
    entry = {"task": task["id"], "standoff": pose, "segments": [], "max_position_error_m": 0.0, "collisions": 0}
    skill = task["skill"]
    try:
        arm = Arm(robot, build, obstacles)
        arm.set_base(pose)
        targets, pos_tol, turns, press = _task_inputs(demo, task, requirements)
        why = None
        if skill not in ("twist_out", "twist_in", "wipe", "pick"):
            why = f"no arm motion is defined for skill {skill!r}"
        elif not targets:
            why = f"task {task['id']} has no reach_targets requirement"
        elif skill.startswith("twist") and not turns:
            why = f"task {task['id']} has no wrist_roll_turns requirement"
        elif arm.collides():  # a new Arm sits at the stowed pose
            why = "the stowed pose itself puts the arm into the base, lift, floor or furniture"
    except (ValueError, KeyError) as e:
        why = f"bad input: {e}"
    if why:
        entry["failure"] = {"segment": "approach", "why": why}
        return entry

    # Several arm poses reach the first target. Try them in a fixed order and keep the first whose
    # whole motion works; if none does, report the one that got furthest.
    rng = np.random.default_rng(0)
    starts = [arm.q_stowed, (arm.lo + arm.hi) / 2]
    best = None
    for k in range(CANDIDATES):
        seed = starts[k] if k < len(starts) else rng.uniform(arm.lo, arm.hi)
        b = _Builder(arm, pos_tol)
        _attempt(b, seed, skill, targets, turns, press)
        # how far it got: the phase, and within the approach whether the grasp pose itself was found (so the
        # failure reported is never "first target: out of reach" when some start did reach it)
        rank = (PHASES.index(b.phase), not b.failure.startswith("first target")) if b.failure else (len(PHASES), True)
        if best is None or rank > best[0]:
            best = (rank, b)
        if not b.failure:
            break
    b = best[1]
    for seg in b.segments:
        if not seg["events"]:
            del seg["events"]
    entry["segments"] = b.segments
    entry["max_position_error_m"] = round(b.max_err, 5)
    entry["collisions"] = b.collisions
    if b.failure:
        entry["failure"] = {"segment": b.phase, "why": b.failure}
    return entry


PHASES = ["approach", "work", "retreat"]


def _attempt(b: _Builder, seed, skill: str, targets: list, turns, press) -> None:
    """Build the whole motion from one starting guess for the grasp pose. Sets b.failure if it cannot."""
    arm = b.arm
    b.phase, b.failure = "approach", None
    try:
        # ---- approach: stowed -> pre-approach in joint space, then straight in along the tool axis
        first = targets[0]
        p_first = np.asarray(first["point"], dtype=float)
        q_at, why = arm.reach(first, seeds=[seed], restarts=0, pos_tol=b.pos_tol, defaults=False)
        if q_at is None:
            raise _Fail(f"first target: {why}")
        a_in = _axis(first)
        back = a_in if a_in is not None else arm.tool_axis()  # axis free: back off along where the tool points
        out = b.line(q_at, p_first, p_first - PRE_APPROACH * back, a_in, a_in)  # solved backwards from the grasp, played forwards
        q_pre = out[-1]
        try:
            move = b.transit(arm.q_stowed, q_pre)
        except _Fail as blocked:  # the direct unfold crosses something: go by a point straight above the pre-approach
            arm.set(q_pre)
            up = dict(first, point=list(arm.tool_pos() + np.array([0.0, 0.0, RAISE_M])))
            q_up, _ = arm.reach(up, seeds=[q_pre], restarts=0, pos_tol=b.pos_tol, defaults=False)
            if q_up is None:
                raise blocked
            b.collisions = 0
            move = b.transit(arm.q_stowed, q_up) + b.transit(q_up, q_pre)
        seg = b.begin("approach", "follow_path", transit="joint")
        if skill != "wipe":
            b.event(seg, "open")
        b.emit(seg, move)
        if skill != "pick":
            b.emit(seg, out[-2::-1] + [q_at])

        # ---- work
        b.phase = "work"
        if skill.startswith("twist"):
            _twist(b, skill, float(turns), p_first, a_in)
        elif skill == "wipe":
            seg = b.begin("work", "wipe", strokes=len(targets) - 1)
            if press is not None:
                seg["press_force_n"] = float(press)
            for t0, t1 in zip(targets, targets[1:]):
                a0, a1 = _axis(t0), _axis(t1)
                if a0 is None or a1 is None:
                    a0 = a1 = None
                b.emit(seg, b.line(b.q, t0["point"], t1["point"], a0, a1, short_ok=WIPE_SHORT_M))
                if b.short:  # the arm ran out of reach just before the end of this stroke
                    seg["short_m"] = round(max(seg.get("short_m", 0.0), b.short), 3)
            if len(targets) == 1:
                b.emit(seg, [b.q] * round(DWELL / DT))
        else:  # pick: descend, close, lift
            seg = b.begin("work", "pick", lift_m=PICK_LIFT)
            b.emit(seg, out[-2::-1] + [q_at])
            b.dwell(seg, "close")
            b.emit(seg, b.line(b.q, p_first, p_first + [0, 0, PICK_LIFT], a_in, a_in))

        # ---- retreat: back off along the tool axis, then joint space to stowed
        b.phase = "retreat"
        seg = b.begin("retreat", "follow_path", transit="joint")
        if skill == "twist_in":
            b.event(seg, "open")
        if skill != "pick":
            arm.set(b.q)
            p_now = arm.tool_pos()
            a_now = _axis(targets[-1]) if skill == "wipe" else a_in
            away = a_now if a_now is not None else arm.tool_axis()
            # Back straight off the work before folding. At the edge of the arm's reach the full distance may
            # not exist along that line, so take the longest of full, half and a quarter that does; with none,
            # fold from where it is (the joint-space move is still checked for collisions).
            seg["back_off_m"], clean = 0.0, b.collisions
            for frac in (1.0, 0.5, 0.25):
                try:
                    back_off = b.line(b.q, p_now, p_now - frac * PRE_APPROACH * away, a_now, a_now)
                except _Fail:
                    b.collisions = clean
                    continue
                b.emit(seg, back_off)
                seg["back_off_m"] = round(frac * PRE_APPROACH, 3)
                break
        try:
            b.emit(seg, b.transit(b.q, arm.q_stowed))
        except _Fail:  # direct way home is blocked: go by the pre-approach pose, whose way home is known clear
            b.emit(seg, b.transit(b.q, q_pre))
            b.emit(seg, move[-2::-1] + [arm.q_stowed])
    except _Fail as e:
        b.failure = str(e)
    except (ValueError, KeyError) as e:  # a target with no point, a zero or reversing tool axis
        b.failure = f"bad target: {e}"


def _twist(b: _Builder, skill: str, turns: float, point, axis) -> None:
    """Hold the grasp pose and roll the last arm joint. A right-hand thread goes in with a positive
    turn about the tool axis (the approach direction) and comes out with a negative one."""
    arm = b.arm
    r = len(arm.names) - 1
    jid = arm.m.joint(arm.names[r]).id
    if arm.m.jnt_type[jid] != mujoco.mjtJoint.mjJNT_HINGE:
        raise _Fail(f"the last arm joint {arm.names[r]} is not a hinge, so it cannot roll the tool")
    arm.set(b.q)
    along = float(arm.d.xaxis[jid] @ arm.tool_axis())
    if abs(along) < 0.9:
        raise _Fail(f"the last arm joint {arm.names[r]} does not turn about the tool axis")
    span = float(arm.hi[r] - arm.lo[r])
    if span <= 1e-6:
        raise _Fail(f"{arm.names[r]} has no range to roll in")
    total = abs(turns) * 2 * math.pi
    way = (1.0 if skill == "twist_in" else -1.0) * math.copysign(1.0, along)  # joint direction while gripping
    strokes = max(1, math.ceil(total / span - 1e-9))
    seg = b.begin("work", "twist", turns=float(turns), regrasps=strokes - 1,
                  direction="in" if skill == "twist_in" else "out", roll_joint=arm.names[r])
    locked = np.zeros(len(arm.names), dtype=bool)
    locked[r] = True

    def roll(to: float) -> None:
        n = max(1, math.ceil(abs(to - b.q[r]) / (ROLL_SPEED * DT)))
        start, q, qs = float(b.q[r]), b.q.copy(), []
        for k in range(1, n + 1):
            q = q.copy()
            q[r] = start + (to - start) * k / n
            # the other joints re-solve around the rolled joint, which is a no-op when the tool sits on its axis
            q, pe, ae = arm.solve(point, axis, q, iters=LINE_ITERS, locked=locked)
            if pe > b.pos_tol or ae > AXIS_TOL_DEG:
                raise _Fail(f"the tool leaves the grasp point while rolling: {pe * 1000:.0f} mm, {ae:.0f} deg off")
            b.max_err = max(b.max_err, pe)
            before = b.collisions
            b.check(q)
            if b.collisions > before:
                raise _Fail(f"rolling {arm.names[r]} swings the wrist into the base, lift or floor")
            qs.append(q)
        b.emit(seg, qs)

    left = total
    for k in range(strokes):
        angle = min(left, span)
        roll(arm.lo[r] if way > 0 else arm.hi[r])  # open: wind up to the far limit (first stroke) or roll back
        b.dwell(seg, "close")
        roll(float(b.q[r]) + way * angle)
        left -= angle
        if k < strokes - 1:
            b.dwell(seg, "open")
