"""Robot renders for the live run view: a transparent PNG of the composed robot at a given pose."""
from __future__ import annotations

import mujoco
import numpy as np

from .. import observe

_renderers: dict = {}


def render(robot_xml: str, qpos: dict | None, label: str, *, pose=None, size: int = 560) -> str | None:
    """Render the robot with joints set from `qpos` ({joint name: value}) and the base at `pose` [x, y, yaw].
    Returns the frame's path relative to the run folder, or None when frames are off or rendering fails."""
    where = observe.frame_path(label)
    if where is None:
        return None
    try:
        from PIL import Image

        m = mujoco.MjModel.from_xml_string(robot_xml)
        d = mujoco.MjData(m)
        for name, v in (qpos or {}).items():
            j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
            if j >= 0:
                d.qpos[m.jnt_qposadr[j]] = v
        if pose is not None:
            for name, v in zip(("joint_x", "joint_y", "joint_th"), pose):
                j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
                if j >= 0:
                    d.qpos[m.jnt_qposadr[j]] = v
        mujoco.mj_forward(m, d)
        floor = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        body = np.array([g for g in range(m.ngeom) if g != floor and m.geom_rgba[g][3] > 0.05])
        lo = (d.geom_xpos[body] - m.geom_rbound[body, None]).min(0)
        hi = (d.geom_xpos[body] + m.geom_rbound[body, None]).max(0)
        centre, span = (lo + hi) / 2, float(np.linalg.norm(hi - lo))
        m.vis.global_.offwidth, m.vis.global_.offheight = max(m.vis.global_.offwidth, size), max(m.vis.global_.offheight, size)
        r = mujoco.Renderer(m, size, size)
        cam = mujoco.MjvCamera()
        cam.lookat[:] = centre
        yaw = float(np.degrees(pose[2])) if pose is not None else 0.0
        cam.distance, cam.azimuth, cam.elevation = max(1.2, span * 1.02), yaw + 140.0, -12.0
        r.update_scene(d, cam)
        rgb = r.render().copy()
        r.enable_segmentation_rendering()
        r.update_scene(d, cam)
        seg = r.render()[:, :, 0]
        r.close()
        alpha = np.where((seg >= 0) & (seg != floor), 255, 0).astype(np.uint8)
        Image.fromarray(np.dstack([rgb, alpha]), "RGBA").save(where[0])
        return where[1]
    except Exception as e:  # a missing GL context or a model that will not load must not stop the run
        observe.emit("note", text=f"render failed for {label}: {type(e).__name__}: {e}")
        return None
