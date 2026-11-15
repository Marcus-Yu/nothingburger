"""Compose a robot from part cards with MuJoCo's MjSpec, and measure the composed model.

Frames: metres, Z up, the robot faces +X, the origin is on the floor under the base centre.
Names in the model: body base_link; joints joint_x, joint_y, joint_th (the planar base) and lift; sites
tool (z is the approach direction), lidar, ego, wrist; prefixes base/ (a legged base), arm/, grip/, sens/.
"""
from __future__ import annotations

import functools
import warnings

import mujoco
import numpy as np

from . import parts as P

warnings.filterwarnings("ignore", message="Attach conflict")

TIP_SF = 1.5
LIDAR_CLEAR = 0.75   # a lidar must see this fraction of the full circle past the robot's own body
ENV_STEP = 0.05      # the reach envelope's grid, in height and in distance
ENV_AXIS_TOL_DEG = 3.0
BOX, CYL = mujoco.mjtGeom.mjGEOM_BOX, mujoco.mjtGeom.mjGEOM_CYLINDER
G = 9.81


def _child(rel: str, drop_free: bool = False):
    """A part's simulator model as a spec ready to attach: keyframes dropped, the root at its origin, and
    every mesh and texture file made absolute so the composed MJCF loads from anywhere."""
    path = P.asset(rel)
    spec = mujoco.MjSpec.from_file(str(path))
    mesh_dir, tex_dir = path.parent / spec.meshdir, path.parent / spec.texturedir
    for me in spec.meshes:
        if me.file:
            me.file = str((mesh_dir / me.file).resolve())
    for tx in spec.textures:
        if tx.file:
            tx.file = str((tex_dir / tx.file).resolve())
    spec.meshdir, spec.texturedir = "", ""
    for k in list(spec.keys):
        spec.delete(k)
    root = spec.worldbody.first_body()
    if root is not None:
        root.pos = [0, 0, 0]  # some models lift their root off the floor for their own scene
        if drop_free:
            for j in list(root.joints):
                if j.type == mujoco.mjtJoint.mjJNT_FREE:
                    spec.delete(j)
    return spec


def _rot(quat):
    m = np.zeros(9)
    mujoco.mju_quat2Mat(m, np.array(quat, dtype=float))
    return m.reshape(3, 3)


def compose_spec(parts: dict):
    """Returns (spec, model, assembly)."""
    parts = P.full(parts)
    P.validate(parts)
    B = P.base_info(parts["base"])
    L, A, Gr = (P.card(s, parts[s]) for s in ("lift", "arm", "gripper"))
    CAM = P.camera()
    assembly = [{"part": parts["base"], "onto": "floor"}]
    spec = mujoco.MjSpec()
    spec.modelname = "robot"
    spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    wb = spec.worldbody
    wb.add_light(pos=[1, -1, 4], dir=[-0.2, 0.2, -1])
    spec.visual.headlight.ambient = [0.45, 0.45, 0.45]
    wb.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[6, 6, 0.1], rgba=[0.85, 0.85, 0.82, 1])
    base = wb.add_body(name="base_link")
    base.add_joint(name="joint_x", type=mujoco.mjtJoint.mjJNT_SLIDE, axis=[1, 0, 0])
    base.add_joint(name="joint_y", type=mujoco.mjtJoint.mjJNT_SLIDE, axis=[0, 1, 0])
    base.add_joint(name="joint_th", type=mujoco.mjtJoint.mjJNT_HINGE, axis=[0, 0, 1])
    if B["kind"] == "wheeled":
        o = B["outline_m"]
        spec.add_mesh(name="base_mesh", file=str(P.asset(B["mesh"]).resolve()), scale=[B["mesh_scale"]] * 3)
        base.add_geom(name="base_visual", type=mujoco.mjtGeom.mjGEOM_MESH, meshname="base_mesh", contype=0, conaffinity=0,
                      mass=0, rgba=[0.6, 0.62, 0.65, 1])
        c = [(o["x"][0] + o["x"][1]) / 2, (o["y"][0] + o["y"][1]) / 2, (o["z"][0] + o["z"][1]) / 2]
        h = [(o["x"][1] - o["x"][0]) / 2, (o["y"][1] - o["y"][0]) / 2, (o["z"][1] - o["z"][0]) / 2]
        base.add_geom(name="base_box", type=BOX, pos=c, size=h, mass=B["mass_kg"], rgba=[0, 0, 0, 0])
        cs = B.get("casters")
        if cs:  # the wheels: drawn, not simulated (the checks use the outline and the support rectangle)
            spec.add_mesh(name="caster_mesh", file=str(P.asset(cs["mesh"]).resolve()), scale=[cs["mesh_scale"]] * 3)
            for i, (x, y, yaw) in enumerate(cs["at"]):
                q = np.zeros(4)
                mujoco.mju_mulQuat(q, np.array([np.cos(np.radians(yaw) / 2), 0, 0, np.sin(np.radians(yaw) / 2)]),
                                   np.array(cs["upright_quat"], dtype=float))
                base.add_geom(name=f"base_caster_{i}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname="caster_mesh", pos=[x, y, 0],
                              quat=q, contype=0, conaffinity=0, mass=0, rgba=[0.16, 0.17, 0.19, 1])
    else:
        base.add_geom(name="base_dummy", type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.001], pos=[0, 0, B["stand_m"]], mass=0,
                      contype=0, conaffinity=0, rgba=[0, 0, 0, 0])
        leg_site = base.add_site(name="legged_mount", pos=[0, 0, B["stand_m"]])
        spec.attach(_child(B["model"], drop_free=True), prefix="base/", site=leg_site)
    mx, _, top = B["mounts"]["top"]
    mount_parent, mount_z, stage = base, top, None
    if L["stroke_m"] > 0:
        r = L["retracted_m"]
        base.add_geom(name="lift_outer", type=BOX, pos=[mx, 0, top + r / 2], size=[0.1, 0.09, r / 2],
                      mass=L["mass_kg"] * 0.6, rgba=[0.25, 0.3, 0.38, 1])
        stage = base.add_body(name="lift_stage", pos=[mx, 0, top])
        stage.add_joint(name="lift", type=mujoco.mjtJoint.mjJNT_SLIDE, axis=[0, 0, 1], range=[0, L["stroke_m"]])
        stage.add_geom(name="lift_inner", type=BOX, pos=[0, 0, r / 2], size=[0.07, 0.06, r / 2 - 0.005],
                       mass=L["mass_kg"] * 0.4, contype=0, conaffinity=0, rgba=[0.7, 0.72, 0.75, 1])
        mount_parent, mount_z = stage, r
        assembly.append({"part": parts["lift"], "onto": f"{parts['base']}:top"})
    mount = mount_parent.add_site(name="arm_mount", pos=[mx if stage is None else 0, 0, mount_z])
    spec.attach(_child(A["model"]), prefix="arm/", site=mount)
    assembly.append({"part": parts["arm"], "onto": f"{parts['lift']}:stage" if stage is not None else f"{parts['base']}:top"})
    if A.get("integrated_gripper"):
        if "tool_frame" in A:  # a model with no tool site: the card gives the point on one of its bodies
            tf = A["tool_frame"]
            hand, tool_pos, tool_quat = spec.body("arm/" + tf["body"]), np.array(tf["pos"], dtype=float), tf["quat"]
        else:
            ee = spec.site("arm/" + A["tool_site"])
            hand, tool_pos, tool_quat = ee.parent, np.array(ee.pos), ee.quat
        assembly.append({"part": parts["gripper"], "onto": f"{parts['arm']}:integrated"})
    else:
        flange = spec.site("arm/" + A["flange_site"])
        spec.attach(_child(Gr["model"]), prefix="grip/", site=flange)
        hand = flange.parent
        if "tool_site" in Gr:
            ts = spec.site("grip/" + Gr["tool_site"])
            hand, tool_pos, tool_quat = ts.parent, np.array(ts.pos), ts.quat
        else:
            tool_pos, tool_quat = np.array(flange.pos) + _rot(flange.quat) @ [0, 0, Gr["tool_offset_m"]], flange.quat
        assembly.append({"part": parts["gripper"], "onto": f"{parts['arm']}:flange"})
    hand.add_site(name="tool", pos=tool_pos, quat=tool_quat)

    # ---- sensors
    fx, _, fz = B["mounts"]["front"]
    li = P.card("lidar", parts["lidar"])
    if parts["lidar"] != "none":
        if parts["lidar_mount"] == "base_front":
            parent, pos, onto = base, [fx, 0, fz + li["height_m"] / 2 + 0.01], f"{parts['base']}:front"
        else:
            parent, pos, onto = stage, [-0.17, 0, L["retracted_m"] + li["height_m"] / 2], f"{parts['lift']}:stage_rear"
        lb = parent.add_body(name="sens/lidar", pos=pos)
        lb.add_geom(name="sens/lidar_body", type=CYL, size=[li["radius_m"], li["height_m"] / 2], mass=li["mass_kg"],
                    contype=0, conaffinity=0, rgba=[0.85, 0.3, 0.1, 1])
        lb.add_site(name="lidar", pos=[0, 0, 0])
        assembly.append({"part": parts["lidar"], "onto": onto})
    if parts["ego_cam"] != "none":
        if parts["ego_cam"] == "base_front":
            parent, pos, onto = base, [fx + 0.03, 0.09, fz + 0.03], f"{parts['base']}:front"
        else:
            parent, pos, onto = stage, [0.14, 0, L["retracted_m"] - 0.03], f"{parts['lift']}:stage_front"
        s = parent.add_site(name="ego_mount", pos=pos, quat=[0.5, 0.5, 0.5, 0.5])
        spec.attach(_child(CAM["model"]), prefix="sens/ego/", site=s)
        parent.add_site(name="ego", pos=pos)
        assembly.append({"part": P.CAMERA, "onto": onto, "as": "ego camera"})
    if parts["wrist_cam"]:
        back = tool_pos - _rot(tool_quat) @ [0, 0, 0.12] + _rot(tool_quat) @ [0.06, 0, 0]
        s = hand.add_site(name="wrist_mount", pos=back, quat=tool_quat)
        spec.attach(_child(CAM["model"]), prefix="sens/wrist/", site=s)
        hand.add_site(name="wrist", pos=back, quat=tool_quat)
        assembly.append({"part": P.CAMERA, "onto": f"{parts['gripper']}:wrist", "as": "wrist camera"})
    model = spec.compile()
    for i, a in enumerate(assembly):
        a.update(step=i + 1)
    return spec, model, [{"step": a.pop("step"), **a} for a in assembly]


_STOW: dict = {}      # (carrier key, width limit, height limit) -> {joint name: value}
_ENVELOPE: dict = {}  # carrier key -> {(axis, height bin): [(distance, {joint name: value}), ...]}


class Robot:
    def __init__(self, parts: dict):
        self.parts = parts = P.full(parts)
        self.B = P.base_info(parts["base"])
        self.spec, self.m, self.assembly = compose_spec(parts)
        self.d = mujoco.MjData(self.m)
        m = self.m
        total, summed = float(m.body_mass.sum()), P.part_mass(parts)
        assert abs(total - summed) < 1e-3, f"mass leak: model {total:.3f} kg, parts {summed:.3f} kg"
        self.mass = total
        self.tool = m.site("tool").id
        self.base_id = m.body("base_link").id
        names = [m.body(m.geom_bodyid[g]).name for g in range(m.ngeom)]
        self.is_arm = np.array([n.startswith(("arm/", "grip/", "sens/wrist/")) for n in names])
        self.is_carrier = np.array([n in ("base_link", "lift_stage") or n.startswith("base/") for n in names])
        self.is_robot = np.array([n != "world" for n in names])
        for skip in ("base_visual", "base_dummy", *(f"base_caster_{i}" for i in range(4))):
            if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, skip) >= 0:
                self.is_carrier[m.geom(skip).id] = False
                self.is_robot[m.geom(skip).id] = False
        self.q0 = m.qpos0.copy()
        for jn, v in self.B.get("home", {}).items():
            self.q0[m.joint("base/" + jn).qposadr] = v
        # the joints that place the tool once the base is parked: the lift, then the arm (no fingers)
        fingers = {"arm/" + n for n in P.card("arm", parts["arm"]).get("finger_joints", [])}
        self.free = [j for j in range(m.njnt)
                     if m.joint(j).name == "lift"
                     or (m.joint(j).name.startswith("arm/") and m.joint(j).name not in fingers
                         and "gripper" not in m.joint(j).name.lower() and "finger" not in m.joint(j).name.lower())]
        self.arm_joints = [m.joint(j).name for j in self.free]
        self.qadr = np.array([m.jnt_qposadr[j] for j in self.free])
        self.dadr = np.array([m.jnt_dofadr[j] for j in self.free])
        lo = np.array([m.jnt_range[j][0] if m.jnt_limited[j] else -np.pi for j in self.free])
        hi = np.array([m.jnt_range[j][1] if m.jnt_limited[j] else np.pi for j in self.free])
        self.lo, self.hi = np.maximum(lo, -2 * np.pi), np.minimum(hi, 2 * np.pi)
        self.is_lift = np.array([n == "lift" for n in self.arm_joints])
        self.stroke = float(self.hi[self.is_lift][0]) if self.is_lift.any() else 0.0
        self._c = P.corners(m)
        self.set(np.clip(np.zeros(len(self.free)), self.lo, self.hi))

    # ---- state
    def set(self, q):
        self.d.qpos[:] = self.q0
        self.d.qpos[self.qadr] = q
        mujoco.mj_kinematics(self.m, self.d)
        mujoco.mj_comPos(self.m, self.d)

    def vec(self, named: dict):
        return np.array([named[n] for n in self.arm_joints])

    def named(self, q) -> dict:
        return {n: round(float(v), 5) for n, v in zip(self.arm_joints, q)}

    def extents(self, mask):
        R = self.d.geom_xmat.reshape(-1, 3, 3)[mask]
        pts = (np.einsum("gij,gkj->gki", R, self._c[mask]) + self.d.geom_xpos[mask][:, None, :]).reshape(-1, 3)
        return pts.min(0), pts.max(0)

    def arm_hits_carrier(self):
        mujoco.mj_collision(self.m, self.d)
        for c in self.d.contact[: self.d.ncon]:
            a, b = c.geom1, c.geom2
            if c.dist < -0.002 and ((self.is_arm[a] and self.is_carrier[b]) or (self.is_arm[b] and self.is_carrier[a])):
                return True
        return False

    # ---- tip-over
    def tip_sf(self, payload_kg=0.0, tool_force=(0.0, 0.0, 0.0)):
        """Static tip-over at the current pose. Forces: gravity on every body, the payload hanging at the tool,
        and `tool_force` (N, world frame) acting on the robot at the tool. For each edge of the support
        rectangle (wheel contacts or feet): the moments that hold the robot down over those that tip it
        outward. Returns the worst edge's ratio."""
        Rb = self.d.xmat[self.base_id].reshape(3, 3)
        pb = self.d.xpos[self.base_id]
        tool = self.d.site_xpos[self.tool]
        pts = np.array([self.d.xipos[b] for b in range(1, self.m.nbody)] + [tool, tool])
        F = np.zeros((len(pts), 3))
        F[:-2, 2] = -self.m.body_mass[1:] * G
        F[-2, 2] = -payload_kg * G
        F[-1] = np.asarray(tool_force, dtype=float)
        loc, Fl = (pts - pb) @ Rb, F @ Rb
        height = pts[:, 2]
        worst = np.inf
        for axis, lim in ((0, self.B["support"]["x"]), (1, self.B["support"]["y"])):
            for edge, sign in ((lim[0], -1.0), (lim[1], 1.0)):
                out = sign * (loc[:, axis] - edge)             # how far outside this edge the force acts
                mom = out * Fl[:, 2] - height * sign * Fl[:, axis]  # > 0 holds the robot down, < 0 tips it
                hold, tip = mom[mom > 0].sum(), -mom[mom < 0].sum()
                worst = min(worst, hold / tip if tip > 1e-9 else np.inf)
        return float(worst)

    # ---- sensors
    def lidar_clear(self):
        """Fraction of the horizontal circle the lidar sees past the robot's own body (out to 1.5 m)."""
        mujoco.mj_kinematics(self.m, self.d)
        o = self.d.site_xpos[self.m.site("lidar").id].copy()
        body = self.m.body("sens/lidar").id
        gid = np.zeros(1, dtype=np.int32)
        clear = []
        for a in np.radians(np.arange(0, 360, 2)):
            dist = mujoco.mj_ray(self.m, self.d, o, np.array([np.cos(a), np.sin(a), 0.0]), None, 1, body, gid)
            clear.append(dist < 0 or dist > 1.5)
        return float(np.mean(clear))

    # ---- stowed pose
    def stow(self, width_limit: float = 0.0, height_limit: float = 0.0, seed: int = 0, n: int = 3000) -> dict:
        """Fold the arm with the lift down. In order: no wider than `width_limit` (if it cannot get that
        narrow, or no limit is given, as narrow as it goes); no taller than `height_limit` (when given);
        sticking out as little as possible past the base's front and rear; then as low as it goes.
        Seeded random search, cached per carrier and limits. Returns the joint values and the robot's
        extents in that pose."""
        ck = (P.carrier_key(self.parts), round(float(width_limit), 3), round(float(height_limit), 3))
        o = self.B["outline_m"]
        base_w, base_l = o["y"][1] - o["y"][0], o["x"][1] - o["x"][0]
        if ck not in _STOW:
            rng = np.random.default_rng(seed)
            cap = max(base_w, width_limit)
            best = None
            arm_idx = np.flatnonzero(~self.is_lift)
            for i in range(2 * n):
                if i < n:
                    q = rng.uniform(self.lo, self.hi)
                    if i % 2 == 0:
                        q[arm_idx[0]] = rng.choice([0, np.pi / 2, np.pi, -np.pi / 2]) + rng.normal(0, 0.05)
                        q = np.clip(q, self.lo, self.hi)
                elif best is None:
                    break
                else:
                    q = np.clip(best[1] + rng.normal(0, 0.08, len(self.lo)), self.lo, self.hi)
                q[self.is_lift] = 0.0
                self.set(q)
                lo, hi = self.extents(self.is_arm | self.is_carrier)
                if lo[2] < -0.01:
                    continue
                width = max(hi[1] - lo[1], base_w)
                over_x = max(hi[0] - o["x"][1], o["x"][0] - lo[0], 0.0)  # how far the arm sticks out fore or aft
                over_h = max(float(hi[2]) - height_limit, 0.0) if height_limit > 0 else 0.0
                score = (round(max(width - cap, 0.0), 3), round(over_h, 3), round(over_x / 0.02), float(hi[2]))
                if (best is None or score < best[0]) and not self.arm_hits_carrier():
                    best = (score, q.copy())
            if best is None:
                raise RuntimeError(f"no stowed pose found for {self.parts}")
            _STOW[ck] = self.named(best[1])
        named = _STOW[ck]
        self.set(self.vec(named))
        lo, hi = self.extents(self.is_robot)
        qpos = dict(named)
        for jn, v in self.B.get("home", {}).items():
            qpos["base/" + jn] = round(v, 5)
        return {"qpos": qpos, "arm": named, "width_m": round(float(max(hi[1] - lo[1], base_w)), 3),
                "length_m": round(float(max(hi[0] - lo[0], base_l)), 3), "height_m": round(float(hi[2]), 3)}

    # ---- reach envelope
    def _align(self, q, a, arm_idx, jr, iters=12):
        """Turn the arm joints until the tool's approach axis lies along `a`. Not a position solve: the tool
        ends up wherever that leaves it, and that point is one sample of the envelope."""
        cos_tol = np.cos(np.radians(ENV_AXIS_TOL_DEG))
        for _ in range(iters):
            self.set(q)
            z = self.d.site_xmat[self.tool].reshape(3, 3)[:, 2]
            if z @ a > cos_tol:
                return q
            mujoco.mj_jacSite(self.m, self.d, None, jr, self.tool)
            J = jr[:, self.dadr[arm_idx]]
            dq = J.T @ np.linalg.solve(J @ J.T + 1e-3 * np.eye(3), np.cross(z, a) if z @ a > -0.99 else np.array([1.0, 0, 0]))
            q = q.copy()
            q[arm_idx] = np.clip(q[arm_idx] + np.clip(dq, -0.6, 0.6), self.lo[arm_idx], self.hi[arm_idx])
        return None

    def envelope(self, seed: int = 0, n: int = 4000) -> dict:
        """Where the tool can be with its approach axis pointing straight up, straight down, and level
        ("side": pointing along the robot's +X, as into a shelf), with the base parked:
        {(axis, height bin): [(distance from the base centre, joint values), ...]}, one entry per ENV_STEP of
        distance. For "side" the distance is measured along the approach axis. Built by sampling the composed model: draw joint values, turn the wrist until
        the tool points up (or down), drop poses where the arm is below the floor or inside the base or
        lift, and record where the tool is. A pose valid at one lift height is taken as valid at every
        higher one (the arm only moves away from the base). Sampled, so the true envelope is a little
        larger at its edges. Cached per carrier."""
        ck = P.carrier_key(self.parts)
        if ck in _ENVELOPE:
            return _ENVELOPE[ck]
        rng = np.random.default_rng(seed)
        arm_idx = np.flatnonzero(~self.is_lift)
        lift_i = int(np.flatnonzero(self.is_lift)[0]) if self.is_lift.any() else None
        jr = np.zeros((3, self.m.nv))
        cells: dict = {}
        mid = np.clip(np.zeros(len(self.lo)), self.lo, self.hi)

        def record(axis, a, q):
            if lift_i is not None:
                q[lift_i] = rng.choice([0.0, rng.uniform(0, self.stroke)])
            q = self._align(q, a, arm_idx, jr)
            if q is None:
                return None
            lo, _ = self.extents(self.is_arm)
            if lo[2] < -0.005 or self.arm_hits_carrier():
                return None
            p = self.d.site_xpos[self.tool]
            # sideways, what counts is how far the tool is past the base centre along its own approach axis:
            # the base stands in front of the shelf or rack and the tool goes straight in
            dist, z = float(p[0]) if axis == "side" else float(np.hypot(p[0], p[1])), float(p[2])
            if dist <= 0:
                return None
            s = float(q[lift_i]) if lift_i is not None else 0.0
            span = self.stroke - s
            for hb in range(int(np.ceil((z - ENV_STEP / 2) / ENV_STEP)), int(np.floor((z + span + ENV_STEP / 2) / ENV_STEP)) + 1):
                if hb < 0:
                    continue
                c = (axis, hb, int(dist / ENV_STEP))
                if c not in cells or dist < cells[c][0]:
                    qq = q.copy()
                    if lift_i is not None:
                        qq[lift_i] = float(np.clip(s + hb * ENV_STEP - z, s, self.stroke))
                    cells[c] = (dist, qq)
            return q

        for axis, a in (("up", np.array([0.0, 0, 1])), ("down", np.array([0.0, 0, -1])), ("side", np.array([1.0, 0, 0]))):
            kept = []
            for i in range(n):
                if i % 3 == 0 and kept:
                    q = np.clip(kept[rng.integers(len(kept))] + rng.normal(0, 0.2, len(self.lo)), self.lo, self.hi)
                elif i % 3 == 1:
                    q = np.clip(mid + rng.normal(0, 0.7, len(self.lo)), self.lo, self.hi)
                else:
                    q = rng.uniform(self.lo, self.hi)
                q = record(axis, a, q)
                if q is not None:
                    kept.append(q)
            for _ in range(2):  # push the edges out: perturb the nearest and farthest pose of every height
                rows = {}
                for (ax, hb, db), (dist, q) in cells.items():
                    if ax == axis:
                        r = rows.setdefault(hb, [(dist, q), (dist, q)])
                        r[0] = min(r[0], (dist, q), key=lambda t: t[0])
                        r[1] = max(r[1], (dist, q), key=lambda t: t[0])
                for hb, ends in rows.items():
                    for dist, q in ends:
                        for _ in range(4):
                            record(axis, a, np.clip(q + rng.normal(0, 0.12, len(self.lo)), self.lo, self.hi))
        table: dict = {}
        for (axis, hb, db), (dist, q) in cells.items():
            table.setdefault((axis, hb), []).append((dist, self.named(q)))
        for v in table.values():
            v.sort(key=lambda t: t[0])
        _ENVELOPE[ck] = table
        return table

    def envelope_rows(self) -> list:
        rows = []
        for (axis, hb), entries in sorted(self.envelope().items(), key=lambda kv: (("down", "up", "side").index(kv[0][0]), kv[0][1])):
            rows.append({"height_m": round(hb * ENV_STEP, 3), "tool_axis": axis,
                         "min_distance_m": round(entries[0][0], 3), "max_distance_m": round(entries[-1][0], 3)})
        return rows

    def envelope_at(self, axis: str, height: float):
        """The envelope's entries at the grid height nearest `height`, or None when the tool cannot be there."""
        return self.envelope().get((axis, int(round(height / ENV_STEP))))

    # ---- wrist roll
    def wrist_roll(self) -> dict:
        """The last arm joint, if it turns about the tool's approach axis: its range in turns."""
        j = self.free[-1]
        self.set(np.clip(np.zeros(len(self.free)), self.lo, self.hi))
        axis = self.d.xmat[self.m.jnt_bodyid[j]].reshape(3, 3) @ self.m.jnt_axis[j]
        z = self.d.site_xmat[self.tool].reshape(3, 3)[:, 2]
        along = bool(self.m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE and abs(float(axis @ z)) > 0.95)
        if not along:
            return {"joint": self.m.joint(j).name, "along_tool": False, "turns": 0.0}
        turns = float(np.diff(self.m.jnt_range[j])[0] / (2 * np.pi)) if self.m.jnt_limited[j] else float("inf")
        return {"joint": self.m.joint(j).name, "along_tool": True, "turns": turns}


@functools.lru_cache(maxsize=12)
def _robot(k: tuple) -> Robot:
    return Robot(dict(zip(P.PART_KEYS, k)))


def robot(parts: dict) -> Robot:
    """The composed robot for these parts (a few are kept in memory)."""
    return _robot(P.key(parts))
