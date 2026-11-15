"""compose: a design -> MJCF text and the build.json dict."""
from __future__ import annotations

import mujoco
import numpy as np

from . import model as M
from . import parts as P

JOINT_TYPES = {int(mujoco.mjtJoint.mjJNT_FREE): "free", int(mujoco.mjtJoint.mjJNT_BALL): "ball",
               int(mujoco.mjtJoint.mjJNT_SLIDE): "slide", int(mujoco.mjtJoint.mjJNT_HINGE): "hinge"}


def robot_xml(robot: M.Robot, stow: dict) -> str:
    """MJCF with absolute mesh paths, plus a keyframe `stowed` (a legged base stands in it; position
    actuators are set to hold it)."""
    m, spec = robot.m, robot.spec
    qpos = robot.q0.copy()
    qpos[robot.qadr] = robot.vec(stow["arm"])
    ctrl = np.zeros(m.nu)
    for a in range(m.nu):
        is_position = m.actuator_biastype[a] == mujoco.mjtBias.mjBIAS_AFFINE and m.actuator_gainprm[a, 0] == -m.actuator_biasprm[a, 1]
        if m.actuator_trntype[a] == mujoco.mjtTrn.mjTRN_JOINT and is_position:
            v = qpos[m.jnt_qposadr[m.actuator_trnid[a, 0]]]
            ctrl[a] = np.clip(v, *m.actuator_ctrlrange[a]) if m.actuator_ctrllimited[a] else v
    for k in list(spec.keys):
        spec.delete(k)
    spec.add_key(name="stowed", qpos=qpos, ctrl=ctrl)
    spec.compile()
    return spec.to_xml()


def build(robot: M.Robot, stow: dict) -> dict:
    parts, B, m = robot.parts, robot.B, robot.m
    o, sup = B["outline_m"], B["support"]
    footprint = P.rect(o["x"], o["y"])
    joints = [{"name": m.joint(j).name, "type": JOINT_TYPES[int(m.jnt_type[j])],
               "range": [round(float(v), 4) for v in m.jnt_range[j]] if m.jnt_limited[j] else None} for j in range(m.njnt)]
    sensors = []
    if parts["lidar"] != "none":
        sensors.append({"kind": "lidar", "part": parts["lidar"], "site": "lidar", "mount": parts["lidar_mount"],
                        "dim": P.card("lidar", parts["lidar"])["dim"]})
    if parts["ego_cam"] != "none":
        sensors.append({"kind": "depth_camera", "part": P.CAMERA, "site": "ego", "mount": parts["ego_cam"]})
    if parts["wrist_cam"]:
        sensors.append({"kind": "depth_camera", "part": P.CAMERA, "site": "wrist", "mount": "wrist"})
    roll = robot.wrist_roll()
    return {
        "schema": "build/1",
        "parts": dict(parts),
        "robot_xml": "robot.xml",
        "mass_kg": round(robot.mass, 2),
        "price_usd": P.price(parts),
        "base": {"kind": B["kind"], "holonomic": bool(B["holonomic"]), "step_max_m": B["step_max_m"],
                 "payload_kg": B["payload_kg"],
                 "footprint": [[round(x, 3), round(y, 3)] for x, y in footprint],
                 "inscribed_radius_m": round(float(min(-o["x"][0], o["x"][1], -o["y"][0], o["y"][1])), 3),
                 "circumscribed_radius_m": round(float(max(np.hypot(x, y) for x, y in footprint)), 3),
                 "support": [[round(x, 3), round(y, 3)] for x, y in P.rect(sup["x"], sup["y"])]},
        "stowed": {"width_m": stow["width_m"], "length_m": stow["length_m"], "height_m": stow["height_m"],
                   "qpos": stow["qpos"], "keyframe": "stowed"},
        "reach_envelope": robot.envelope_rows(),
        "reach_envelope_note": (
            "One row per height (above the floor) and tool_axis. tool_axis 'down': the tool's approach axis points "
            "straight down; 'up': straight up; 'side': level, along the robot's +X. min/max_distance_m: horizontal distance from the base centre to the "
            f"tool, over the lift's travel, base parked. Sampled from the composed model on a {M.ENV_STEP} m grid; "
            "poses with the arm in the floor, the base or the lift are left out."),
        "joints": joints,
        "arm_joints": list(robot.arm_joints),
        "wrist_roll": {"joint": roll["joint"], "turns": None if np.isinf(roll["turns"]) else round(roll["turns"], 3)},
        "tool_site": "tool",
        "sensors": sensors,
        "assembly": robot.assembly,
    }


def compose(design: dict, requirements: dict | None = None) -> dict:
    parts = design.get("parts", design) if isinstance(design, dict) else None
    if not parts:
        raise ValueError("compose needs a design with parts (an infeasible design has none)")
    robot = M.robot(parts)
    # fold the arm to the same limits `check` used: from the ledger when given, else from the design's own checks
    width, height = 0.0, 0.0
    if requirements is not None:
        from .checks import Ledger
        L = Ledger(requirements)
        width = L.number("base_width_max", None, min)[0] or 0.0
        height = L.number("stowed_height_max", None, min)[0] or 0.0
    else:
        for c in design.get("checks") or []:
            if c.get("check") == "doorway" and isinstance(c.get("limit"), (int, float)):
                width = float(c["limit"])
            if c.get("check") == "door header" and isinstance(c.get("limit"), (int, float)):
                height = float(c["limit"])
    stow = robot.stow(width, height)
    return {"robot_xml": robot_xml(robot, stow), "build": build(robot, stow)}
