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


# ------------------------------------------------------------------ the room from above

TOP_PX = 1100          # the top view is a square image this many pixels a side
WALL_H, WALL_T = 1.1, 0.07   # walls are drawn cut off at this height so the camera sees into the rooms
FLOORS = {"atrium": (0.80, 0.68, 0.50), "hallway": (0.74, 0.72, 0.68), "kitchen": (0.80, 0.78, 0.72), "bathroom": (0.78, 0.83, 0.85), "bedroom": (0.72, 0.62, 0.50),
          "living_room": (0.70, 0.60, 0.48), "server_hall": (0.62, 0.65, 0.68), "workshop": (0.60, 0.61, 0.60),
          "plant_room": (0.58, 0.60, 0.58), "yard": (0.50, 0.56, 0.46), "waiting_room": (0.76, 0.74, 0.70)}
FURNITURE = (("cloth_table", (0.93, 0.56, 0.13)), ("stairs", (0.62, 0.63, 0.64)), ("rail", (0.75, 0.82, 0.85)), ("rack", (0.16, 0.17, 0.20)), ("bed", (0.55, 0.66, 0.80)), ("sofa", (0.45, 0.52, 0.47)), ("chair", (0.45, 0.52, 0.47)),
             ("counter", (0.86, 0.85, 0.82)), ("vanity", (0.90, 0.90, 0.88)), ("bath", (0.93, 0.94, 0.95)), ("cnc", (0.30, 0.42, 0.52)),
             ("pump", (0.25, 0.45, 0.40)), ("pallet", (0.66, 0.52, 0.36)), ("shelf", (0.55, 0.57, 0.60)), ("sill", (0.92, 0.91, 0.88)),
             ("ledge", (0.80, 0.70, 0.55)), ("table", (0.62, 0.47, 0.33)), ("stool", (0.62, 0.47, 0.33)))
_top: dict = {}


def top_extent(world: dict) -> list:
    """[x0, y0, x1, y1]: the square of floor the top view shows (the rooms plus a margin)."""
    pts = np.array([p for r in world["rooms"] for p in r["polygon"]], dtype=float)
    lo, hi = pts.min(0), pts.max(0)
    c, half = (lo + hi) / 2, float((hi - lo).max()) / 2 + 0.6
    return [float(c[0] - half), float(c[1] - half), float(c[0] + half), float(c[1] + half)]


def _wall_runs(world: dict):
    """Wall segments [(x0, y0, x1, y1)]: every room edge, with a gap at each doorway on it."""
    out = []
    for room in world["rooms"]:
        if room.get("type") == "yard":
            continue
        poly = [np.array(p, dtype=float) for p in room["polygon"]]
        for a, b in zip(poly, poly[1:] + poly[:1]):
            length = float(np.linalg.norm(b - a))
            if length < 1e-6:
                continue
            u = (b - a) / length
            gaps = []
            for d in world.get("doorways", []):
                p = np.array(d["position"][:2], dtype=float) - a
                s, off = float(p @ u), abs(float(p[0] * u[1] - p[1] * u[0]))
                if off < 0.08 and -1e-6 <= s <= length + 1e-6 and room["id"] in d.get("rooms", [room["id"]]):
                    gaps.append((s - d["width_m"] / 2, s + d["width_m"] / 2))
            at = 0.0
            for g0, g1 in sorted(gaps) + [(length, length)]:
                if g0 - at > 0.02:
                    out.append((*(a + u * at), *(a + u * min(g0, length))))
                at = max(at, g1)
    return out


def _top_scene(world: dict, robot_xml: str | None):
    """(model, data, renderer, camera, robot geom mask) for the world seen from straight above (parallel
    projection), cached."""
    key = (world.get("id"), len(str(world)), hash(robot_xml))
    if key in _top:
        return _top[key]
    spec = mujoco.MjSpec.from_string(robot_xml) if robot_xml else mujoco.MjSpec()
    if robot_xml:
        spec.geom("floor").rgba = [0, 0, 0, 0]
    spec.visual.global_.offwidth = spec.visual.global_.offheight = TOP_PX
    spec.visual.headlight.ambient = [0.34, 0.34, 0.34]
    spec.visual.headlight.diffuse = [0.16, 0.16, 0.16]
    spec.visual.headlight.specular = [0, 0, 0]
    spec.visual.quality.shadowsize = 4096
    wb = spec.worldbody
    x0, y0, x1, y1 = top_extent(world)
    wb.add_light(pos=[(x0 + x1) / 2 - 2.0, (y0 + y1) / 2 - 1.5, 7.0], dir=[0.25, 0.2, -1.0], diffuse=[0.42, 0.42, 0.40], specular=[0, 0, 0],
                 type=mujoco.mjtLightType.mjLIGHT_DIRECTIONAL, castshadow=True)
    box = mujoco.mjtGeom.mjGEOM_BOX
    for r in world["rooms"]:
        p = np.array(r["polygon"], dtype=float)
        lo, hi = p.min(0), p.max(0)
        rgb = FLOORS.get(r.get("type"), (0.74, 0.72, 0.68))
        wb.add_geom(type=box, pos=[*(lo + hi) / 2, -0.02], size=[*(hi - lo) / 2, 0.02], rgba=[*rgb, 1], contype=0, conaffinity=0)
    for ax, ay, bx, by in _wall_runs(world):
        length, yaw = float(np.hypot(bx - ax, by - ay)), float(np.arctan2(by - ay, bx - ax))
        wb.add_geom(type=box, pos=[(ax + bx) / 2, (ay + by) / 2, WALL_H / 2], size=[length / 2 + WALL_T / 2, WALL_T / 2, WALL_H / 2],
                    quat=[np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)], rgba=[0.93, 0.92, 0.89, 1], contype=0, conaffinity=0)
    for o in world.get("obstacles", []):
        lo, hi = np.array(o["box"]["min"], dtype=float), np.array(o["box"]["max"], dtype=float)
        rgb = next((c for k, c in FURNITURE if k in o["id"]), (0.60, 0.58, 0.55))
        wb.add_geom(type=box, pos=list((lo + hi) / 2), size=list(np.maximum((hi - lo) / 2, 0.005)), rgba=[*rgb, 1], contype=0, conaffinity=0)
    m = spec.compile()
    d = mujoco.MjData(m)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [(x0 + x1) / 2, (y0 + y1) / 2, 0.0]
    cam.azimuth, cam.elevation = 90.0, -90.0
    # a parallel projection, so a tall rack or the robot's arm is drawn where it stands, not leaning away
    # from the image centre; with it, fovy is the height of the view in metres
    cam.orthographic, cam.distance = 1, 20.0
    m.vis.global_.orthographic, m.vis.global_.fovy = 1, x1 - x0
    robot = np.array([m.geom_bodyid[g] != 0 for g in range(m.ngeom)])
    _top[key] = (m, d, mujoco.Renderer(m, TOP_PX, TOP_PX), cam, robot)
    return _top[key]


def room_view(world: dict) -> dict | None:
    """Render the rooms, walls and furniture from straight above. Returns {"frame", "extent"} (the image and
    the floor square [x0, y0, x1, y1] it covers), or None when frames are off or rendering fails."""
    where = observe.frame_path("room-top")
    if where is None:
        return None
    try:
        from PIL import Image

        m, d, r, cam, _ = _top_scene(world, None)
        mujoco.mj_forward(m, d)
        r.update_scene(d, cam)
        rgb = r.render().copy()
        r.enable_segmentation_rendering()
        r.update_scene(d, cam)
        seg = r.render()[:, :, 0]
        r.disable_segmentation_rendering()
        alpha = np.where(seg >= 0, 255, 0).astype(np.uint8)  # nothing outside the building
        Image.fromarray(np.dstack([rgb, alpha]), "RGBA").save(where[0])
        return {"frame": where[1], "extent": [round(v, 3) for v in top_extent(world)]}
    except Exception as e:
        observe.emit("note", text=f"top view failed: {type(e).__name__}: {e}")
        return None


def robot_top(world: dict, robot_xml: str, qpos: dict | None, pose, label: str) -> str | None:
    """The robot alone, seen from straight above at `pose` in the same square as room_view: a transparent
    PNG to lay over the room image. Returns the frame's path relative to the run folder, or None."""
    where = observe.frame_path("top-" + label)
    if where is None:
        return None
    try:
        from PIL import Image

        m, d, r, cam, robot = _top_scene(world, robot_xml)
        mujoco.mj_resetData(m, d)
        for name, v in {**(qpos or {}), **dict(zip(("joint_x", "joint_y", "joint_th"), pose))}.items():
            j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
            if j >= 0:
                d.qpos[m.jnt_qposadr[j]] = v
        mujoco.mj_forward(m, d)
        r.disable_segmentation_rendering()
        r.update_scene(d, cam)
        rgb = r.render().copy()
        r.enable_segmentation_rendering()
        r.update_scene(d, cam)
        seg = r.render()[:, :, 0]
        r.disable_segmentation_rendering()
        ids = np.flatnonzero(robot & (m.geom_rgba[:, 3] > 0.05))
        alpha = np.where(np.isin(seg, ids), 255, 0).astype(np.uint8)
        Image.fromarray(np.dstack([rgb, alpha]), "RGBA").save(where[0])
        return where[1]
    except Exception as e:
        observe.emit("note", text=f"top view failed for {label}: {type(e).__name__}: {e}")
        return None
