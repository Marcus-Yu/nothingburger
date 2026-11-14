"""Inverse kinematics at a parked base pose, the self-collision test and the static tip-over ratio.

The solver is damped least squares on MuJoCo's site Jacobian (no mink): the base joints are pinned
at the standoff pose, the free joints are exactly `build["arm_joints"]`, and every step is clipped
to the joint ranges. Restarts are seeded, so the same inputs give the same answer.
"""
from __future__ import annotations

import functools

import mujoco
import numpy as np
from scipy.spatial import ConvexHull

POS_TOL = 0.01  # m: a target counts as reached inside this
AXIS_TOL_DEG = 10.0
SOLVE_POS = 5e-4  # the solver keeps iterating down to this, so paths track far inside POS_TOL
SOLVE_AXIS_DEG = 0.5
TIP_MIN = 1.5
TIP_CAP = 99.0  # an arm that loads no edge has an unbounded ratio; JSON has no infinity
PENETRATION = 0.002  # m: contacts shallower than this are touching, not hitting
DAMPING = 1e-3
STEP_MAX = 0.3  # rad (m for the lift) per iteration
RESTARTS = 10
ITERS = 200
G = 9.81


@functools.lru_cache(maxsize=8)
def _model(robot_xml: str) -> mujoco.MjModel:
    return mujoco.MjModel.from_xml_string(robot_xml)


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-9:
        raise ValueError("zero-length direction")
    return v / n


class Arm:
    """One robot model with its base parked. `q` is always the vector of `build["arm_joints"]`."""

    def __init__(self, robot_xml: str, build: dict):
        self.m = m = _model(robot_xml)
        self.d = mujoco.MjData(m)
        self.names = list(build["arm_joints"])
        if not self.names:
            raise ValueError("build['arm_joints'] is empty")
        jid = []
        for n in self.names + ["joint_x", "joint_y", "joint_th"]:
            j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, n)
            if j < 0:
                raise ValueError(f"joint {n!r} is not in the robot model")
            jid.append(j)
        jid, base_j = jid[:-3], jid[-3:]
        self.qadr = np.array([m.jnt_qposadr[j] for j in jid])
        self.dadr = np.array([m.jnt_dofadr[j] for j in jid])
        self.base_adr = np.array([m.jnt_qposadr[j] for j in base_j])
        self.tool = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, build["tool_site"])
        if self.tool < 0:
            raise ValueError(f"tool site {build['tool_site']!r} is not in the robot model")
        self.base_id = m.body("base_link").id

        # ranges: the model's, narrowed by the build's where it gives one; unlimited hinges get one turn each way
        given = {j["name"]: j.get("range") for j in build.get("joints", [])}
        lo, hi = [], []
        for n, j in zip(self.names, jid):
            a, b = (m.jnt_range[j] if m.jnt_limited[j] else (-2 * np.pi, 2 * np.pi))
            if given.get(n):
                a, b = max(a, given[n][0]), min(b, given[n][1])
            lo.append(max(a, -2 * np.pi) if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE else a)
            hi.append(min(b, 2 * np.pi) if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE else b)
        self.lo, self.hi = np.array(lo), np.array(hi)

        # every other joint is held: the model's default pulled inside its range, then the build's stowed values
        self.q_hold = m.qpos0.copy()
        for j in range(m.njnt):
            if m.jnt_limited[j] and m.jnt_type[j] in (mujoco.mjtJoint.mjJNT_HINGE, mujoco.mjtJoint.mjJNT_SLIDE):
                a = m.jnt_qposadr[j]
                self.q_hold[a] = np.clip(self.q_hold[a], *m.jnt_range[j])
        for n, v in (build.get("stowed", {}).get("qpos") or {}).items():
            j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, n)
            if j >= 0:
                self.q_hold[m.jnt_qposadr[j]] = v
        self.q_stowed = np.clip(self.q_hold[self.qadr], self.lo, self.hi)

        body_names = [m.body(m.geom_bodyid[g]).name for g in range(m.ngeom)]
        self.is_arm = np.array([n.startswith(("arm/", "grip/", "sens/wrist/")) for n in body_names])
        # what the arm must not hit: the base, the lift, a legged base's legs, and the floor (world geoms)
        self.is_obstacle = np.array([n in ("base_link", "lift_stage", "world") or n.startswith("base/") for n in body_names])
        self.is_obstacle &= (m.geom_contype != 0) | (m.geom_conaffinity != 0)

        sup = np.asarray(build["base"]["support"], dtype=float)
        self.support = sup[ConvexHull(sup).vertices]  # counter-clockwise, whatever order the build gave
        self._jp, self._jr = np.zeros((3, m.nv)), np.zeros((3, m.nv))
        self.set_base([0.0, 0.0, 0.0])
        self.set(self.q_stowed)

    # ---- state

    def set_base(self, pose) -> None:
        self.q_hold[self.base_adr] = np.asarray(pose, dtype=float)

    def set(self, q) -> None:
        self.d.qpos[:] = self.q_hold
        self.d.qpos[self.qadr] = q
        mujoco.mj_kinematics(self.m, self.d)
        mujoco.mj_comPos(self.m, self.d)

    def tool_pos(self) -> np.ndarray:
        return self.d.site_xpos[self.tool].copy()

    def tool_axis(self) -> np.ndarray:
        return self.d.site_xmat[self.tool].reshape(3, 3)[:, 2].copy()

    def errors(self, point, axis) -> tuple[float, float]:
        """Position error in metres and tool-axis error in degrees at the current state."""
        pe = float(np.linalg.norm(np.asarray(point) - self.d.site_xpos[self.tool]))
        ae = float(np.degrees(np.arccos(np.clip(self.tool_axis() @ axis, -1.0, 1.0)))) if axis is not None else 0.0
        return pe, ae

    def within(self, q) -> bool:
        return bool(np.all(q >= self.lo - 1e-9) and np.all(q <= self.hi + 1e-9))

    # ---- checks

    def collides(self) -> bool:
        """Arm, gripper or wrist camera against the base, lift, legs or floor, at the current state."""
        mujoco.mj_collision(self.m, self.d)
        for c in self.d.contact[: self.d.ncon]:
            a, b = c.geom1, c.geom2
            if c.dist < -PENETRATION and ((self.is_arm[a] and self.is_obstacle[b]) or (self.is_arm[b] and self.is_obstacle[a])):
                return True
        return False

    def tip_ratio(self, payload_kg: float = 0.0, tool_force_z_n: float = 0.0) -> float:
        """Static tip-over ratio at the current state. Vertical forces only: gravity on every body,
        the payload hanging at the tool, and `tool_force_z_n`, the world's vertical force on the tool
        (positive up: pressing down on a counter with 10 N gives +10, pushing up on a ceiling gives a
        negative value). For each edge of the support polygon: the moment holding the robot down over
        the moment tipping it. The worst edge, capped at TIP_CAP."""
        m, d = self.m, self.d
        Rb, pb = d.xmat[self.base_id].reshape(3, 3), d.xpos[self.base_id]
        pts = np.vstack([d.xipos[1:], d.site_xpos[self.tool], d.site_xpos[self.tool]])
        fz = np.concatenate([-m.body_mass[1:] * G, [-payload_kg * G, tool_force_z_n]])
        loc = ((pts - pb) @ Rb)[:, :2]
        worst = np.inf
        n = len(self.support)
        for i in range(n):
            a, b = self.support[i], self.support[(i + 1) % n]
            e = (b - a) / np.linalg.norm(b - a)
            inward = np.array([-e[1], e[0]])  # left of a counter-clockwise edge
            mom = -fz * ((loc - a) @ inward)
            hold, tip = mom[mom > 0].sum(), -mom[mom < 0].sum()
            worst = min(worst, hold / tip if tip > 1e-9 else np.inf)
        return float(min(worst, TIP_CAP))

    # ---- solver

    def solve(self, point, axis, q0, *, iters: int = ITERS, locked=None, pos_tol: float = SOLVE_POS,
              axis_tol_deg: float = SOLVE_AXIS_DEG) -> tuple[np.ndarray, float, float]:
        """Damped least squares from `q0`. `point` or `axis` may be None (that part is then free).
        `locked` is a boolean mask of free joints to leave alone. Returns (q, position error m,
        axis error deg); the caller decides what error is acceptable."""
        q = np.clip(np.asarray(q0, dtype=float), self.lo, self.hi)
        move = np.ones(len(q), dtype=bool) if locked is None else ~np.asarray(locked)
        dadr = self.dadr[move]
        best, stall = np.inf, 0
        for _ in range(iters):
            self.set(q)
            rows_e, rows_j = [], []
            pe = ae = 0.0
            mujoco.mj_jacSite(self.m, self.d, self._jp, self._jr, self.tool)
            if point is not None:
                e = np.asarray(point) - self.d.site_xpos[self.tool]
                pe = float(np.linalg.norm(e))
                rows_e.append(e)
                rows_j.append(self._jp[:, dadr])
            if axis is not None:
                z = self.d.site_xmat[self.tool].reshape(3, 3)[:, 2]
                c = float(np.clip(z @ axis, -1.0, 1.0))
                ae = float(np.degrees(np.arccos(c)))
                w = np.cross(z, axis)
                if c < 0:  # past 90 degrees the cross product shrinks again: keep turning at full rate
                    nw = np.linalg.norm(w)
                    w = w / nw if nw > 1e-6 else np.cross(z, [1.0, 0, 0] if abs(z[0]) < 0.9 else [0, 1.0, 0])
                rows_e.append(w)
                rows_j.append((np.eye(3) - np.outer(z, z)) @ self._jr[:, dadr])
            if pe < pos_tol and ae < axis_tol_deg:
                break
            score = pe + np.radians(ae) * 0.1
            stall = stall + 1 if score > best - 1e-6 else 0
            best = min(best, score)
            if stall > 25:
                break
            e, J = np.concatenate(rows_e), np.vstack(rows_j)
            dq = J.T @ np.linalg.solve(J @ J.T + DAMPING * np.eye(len(e)), e)
            q[move] = np.clip(q[move] + np.clip(dq, -STEP_MAX, STEP_MAX), self.lo[move], self.hi[move])
        self.set(q)
        pe, ae = self.errors(point if point is not None else self.tool_pos(), axis)
        return q, pe, ae

    def reach(self, target: dict, *, seeds=(), rng=None, restarts: int = RESTARTS,
              pos_tol: float = POS_TOL, defaults: bool = True) -> tuple[np.ndarray | None, str]:
        """A collision-free joint vector for one reach target, or (None, why). Tries `seeds` first
        (warm starts), then (with `defaults`) the stowed pose and mid-range, then seeded random starts. Leaves the model at the answer."""
        held = target.get("held_axes", ["position", "tool_axis"])
        point = np.asarray(target["point"], dtype=float) if "position" in held else None
        axis = unit(target["tool_axis"]) if "tool_axis" in held and target.get("tool_axis") is not None else None
        if point is None and axis is None:
            return self.q_stowed.copy(), ""
        rng = rng or np.random.default_rng(0)
        closest, hit = np.inf, 0
        starts = [np.asarray(s, dtype=float) for s in seeds] + ([self.q_stowed, (self.lo + self.hi) / 2] if defaults else [])
        for k in range(len(starts) + restarts):
            q0 = starts[k] if k < len(starts) else rng.uniform(self.lo, self.hi)
            q, pe, ae = self.solve(point, axis, q0)
            if pe > pos_tol or ae > AXIS_TOL_DEG:
                closest = min(closest, pe if pe > pos_tol else 0.0)
                continue
            if self.collides():
                hit += 1
                continue
            return q, ""
        if hit:
            return None, "every pose found puts the arm into the base, lift or floor"
        if closest > 0 and np.isfinite(closest):
            return None, f"out of reach, closest miss {closest:.2f} m"
        return None, "position reached but not with the tool axis"


def reachable(robot_xml: str, pose, targets, *, build: dict, payload_kg: float = 0.0, tool_force_z_n: float = 0.0) -> dict:
    arm = Arm(robot_xml, build)
    arm.set_base(pose)
    rng = np.random.default_rng(0)
    q_first, missed, whys, tips = None, [], [], []
    prev = None
    for i, t in enumerate(targets):
        q, why = arm.reach(t, seeds=[] if prev is None else [prev], rng=rng)
        if q is None:
            missed.append(i)
            whys.append(f"target {i}: {why}")
            continue
        prev = q
        if i == 0:
            q_first = q
        tips.append((arm.tip_ratio(payload_kg, tool_force_z_n), i))
    tip, tip_i = min(tips) if tips else (0.0, None)
    if not targets:
        whys.append("no targets given")
    if tips and tip < TIP_MIN:
        whys.append(f"tip ratio {tip:.2f} at target {tip_i} is under {TIP_MIN}")
    ok = bool(targets) and not missed and tip >= TIP_MIN
    return {
        "ok": ok,
        "q": {} if q_first is None else {n: round(float(v), 5) for n, v in zip(arm.names, q_first)},
        "tip_ratio": round(float(tip), 2),
        "missed": missed,
        "why": "; ".join(whys) if whys else f"all {len(targets)} targets reached, worst tip ratio {tip:.2f}",
    }
