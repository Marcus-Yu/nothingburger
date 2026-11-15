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

        # a disc of ground under the base, so the wheels or feet are seen standing on something (on the page's
        # dark background the dark tyres otherwise vanish and the base reads as a floating frame)
        spec = mujoco.MjSpec.from_string(robot_xml)
        spec.body("base_link").add_geom(name="ground_disc", type=mujoco.mjtGeom.mjGEOM_CYLINDER, size=[0.62, 0.002, 0], pos=[0, 0, 0.002],
                                        rgba=[0.80, 0.79, 0.76, 1], contype=0, conaffinity=0, mass=0)
        m = spec.compile()
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
        disc = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "ground_disc")
        body = np.array([g for g in range(m.ngeom) if g not in (floor, disc) and m.geom_rgba[g][3] > 0.05])
        lo = (d.geom_xpos[body] - m.geom_rbound[body, None]).min(0)
        hi = (d.geom_xpos[body] + m.geom_rbound[body, None]).max(0)
        centre, span = (lo + hi) / 2, float(np.linalg.norm(hi - lo))
        m.vis.global_.offwidth, m.vis.global_.offheight = max(m.vis.global_.offwidth, size), max(m.vis.global_.offheight, size)
        r = mujoco.Renderer(m, size, size)
        cam = mujoco.MjvCamera()
        cam.lookat[:] = centre
        yaw = float(np.degrees(pose[2])) if pose is not None else 0.0
        cam.distance, cam.azimuth, cam.elevation = max(1.2, span * 1.02), yaw + 140.0, -5.0
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
WALK_W, WALK_H, WALK_FPS = 960, 540, 24
DRIVE_MPS, TURN_RPS = 0.6, 1.2   # how fast the base is shown driving and turning (assumed; no card gives base speeds)
DRIVE_X, ARM_X = 5.0, 10.0       # the film runs this many times faster than the motion, driving and arm work


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


def _top_scene(world: dict, robot_xml: str | None, top: bool = True):
    """(model, data, renderer, camera, robot geom mask) for the world seen from straight above (parallel
    projection), cached."""
    key = (world.get("id"), len(str(world)), hash(robot_xml), top)
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
        if "table" in o["id"] and hi[2] - lo[2] > 0.5:  # a table is a top on four legs, not a solid block
            skirt = 0.30 if "cloth" in o["id"] else 0.04  # a tablecloth hangs part of the way down
            for sx in (-1, 1):
                for sy in (-1, 1):
                    c = (lo + hi) / 2 + np.array([sx * ((hi[0] - lo[0]) / 2 - 0.06), sy * ((hi[1] - lo[1]) / 2 - 0.06), 0])
                    wb.add_geom(type=box, pos=[c[0], c[1], (lo[2] + hi[2] - skirt) / 2], size=[0.02, 0.02, (hi[2] - lo[2] - skirt) / 2],
                                rgba=[0.25, 0.25, 0.27, 1], contype=0, conaffinity=0)
            lo = np.array([lo[0], lo[1], hi[2] - skirt])
        wb.add_geom(type=box, pos=list((lo + hi) / 2), size=list(np.maximum((hi - lo) / 2, 0.005)), rgba=[*rgb, 1], contype=0, conaffinity=0)
    if not top:  # the film looks across the floor, so there has to be something beyond the building
        wb.add_geom(type=box, pos=[(x0 + x1) / 2, (y0 + y1) / 2, -0.06], size=[x1 - x0 + 20, y1 - y0 + 20, 0.01], rgba=[0.20, 0.21, 0.22, 1],
                    contype=0, conaffinity=0)
    m = spec.compile()
    d = mujoco.MjData(m)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [(x0 + x1) / 2, (y0 + y1) / 2, 0.0]
    cam.azimuth, cam.elevation = 90.0, -90.0
    # a parallel projection, so a tall rack or the robot's arm is drawn where it stands, not leaning away
    # from the image centre; with it, fovy is the height of the view in metres
    if top:
        cam.orthographic, cam.distance = 1, 20.0
        m.vis.global_.orthographic, m.vis.global_.fovy = 1, x1 - x0
    robot = np.array([m.geom_bodyid[g] != 0 for g in range(m.ngeom)])
    _top[key] = (m, d, mujoco.Renderer(m, TOP_PX, TOP_PX) if top else mujoco.Renderer(m, WALK_H, WALK_W), cam, robot)
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


# ------------------------------------------------------------------ the planned job, played through the room


def _timeline(build: dict, route: dict, trajectory: dict):
    """The plan as film frames: [(base pose [x, y, yaw], {joint: value})] and chapters [(frame index, label)].
    The base drives each leg's waypoints (turn, then go), and at each stop the arm plays that stop's samples
    from trajectory.json. Positions only: nothing is simulated."""
    stowed = dict((build.get("stowed") or {}).get("qpos") or {})
    names = trajectory.get("joints") or build.get("arm_joints") or []
    by_pose = {tuple(round(float(v), 3) for v in e["standoff"]): e for e in trajectory.get("tasks", [])}
    frames, chapters = [], []
    pose = [float(v) for v in route["legs"][0]["waypoints"][0]] if route.get("legs") else None

    def wrap(a):
        return (a + np.pi) % (2 * np.pi) - np.pi

    for leg in route.get("legs", []):
        chapters.append((len(frames), f"drive: {leg['from']} to {leg['to']}" + (" (carrying)" if leg.get("carrying") else "")))
        for wp in leg["waypoints"]:
            wp = [float(v) for v in wp]
            dist, turn = float(np.hypot(wp[0] - pose[0], wp[1] - pose[1])), abs(wrap(wp[2] - pose[2]))
            n = max(1, int(np.ceil(max(dist / DRIVE_MPS, turn / TURN_RPS) / DRIVE_X * WALK_FPS)))
            for k in range(1, n + 1):
                f = k / n
                frames.append(([pose[0] + (wp[0] - pose[0]) * f, pose[1] + (wp[1] - pose[1]) * f, pose[2] + wrap(wp[2] - pose[2]) * f], stowed))
            pose = wp
        entry = by_pose.get(tuple(round(v, 3) for v in pose))
        if entry is None or leg.get("to") == "dock":
            continue
        for seg in entry.get("segments", []):
            samples = seg.get("samples") or []
            if not samples:
                continue
            label = {"approach": "reach in", "work": seg.get("kind", "work"), "retreat": "fold away"}.get(seg.get("phase"), seg.get("phase"))
            chapters.append((len(frames), f"{entry['task']}: {label}" + (f" ({entry['covers']})" if entry.get("covers") and seg.get("phase") == "work" else "")))
            t0, t1 = float(samples[0]["t"]), float(samples[-1]["t"])
            ts = np.array([float(x["t"]) for x in samples])
            for k in range(max(1, int(np.ceil((t1 - t0) / ARM_X * WALK_FPS)))):
                i = min(int(np.searchsorted(ts, t0 + k * ARM_X / WALK_FPS)), len(samples) - 1)
                frames.append((pose, {**stowed, **dict(zip(names, samples[i]["q"]))}))
    return frames, chapters


def walkthrough(world: dict, robot_xml: str, build: dict, route: dict, trajectory: dict) -> dict | None:
    """Film the planned job: the robot drives its route through the rendered rooms and runs each arm motion,
    with the camera following. Written as frames/walkthrough.mp4 (needs ffmpeg on the PATH). Returns
    {"video", "seconds", "chapters": [{"t", "label"}], "note"} or None when frames are off or it cannot be made.
    This plays the plan's positions back; it is not a physics simulation."""
    import shutil
    import subprocess

    where = observe.frame_path("walkthrough")
    if where is None:
        return None
    try:
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is not installed")
        frames, chapters = _timeline(build, route, trajectory)
        if not frames:
            raise RuntimeError("the route has no legs")
        m, d, r, cam, _ = _top_scene(world, robot_xml, top=False)
        jadr = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j): m.jnt_qposadr[j] for j in range(m.njnt)}
        video = where[0].with_name("walkthrough.mp4")
        ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WALK_W}x{WALK_H}",
                               "-r", str(WALK_FPS), "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "27",
                               "-movflags", "+faststart", str(video)], stdin=subprocess.PIPE)
        cam.azimuth, cam.elevation, cam.distance = 62.0, -30.0, 4.6
        look = np.array([frames[0][0][0], frames[0][0][1], 0.5])
        for pose, q in frames:
            mujoco.mj_resetData(m, d)
            for name, v in {**q, "joint_x": pose[0], "joint_y": pose[1], "joint_th": pose[2]}.items():
                if name in jadr:
                    d.qpos[jadr[name]] = v
            mujoco.mj_forward(m, d)
            look += 0.12 * (np.array([pose[0], pose[1], 0.5]) - look)  # the camera eases after the robot
            cam.lookat[:] = look
            r.update_scene(d, cam)
            ff.stdin.write(r.render().tobytes())
        ff.stdin.close()
        if ff.wait() != 0:
            raise RuntimeError("ffmpeg failed")
        return {"video": f"frames/{video.name}", "seconds": round(len(frames) / WALK_FPS, 1),
                "chapters": [{"t": round(i / WALK_FPS, 1), "label": label} for i, label in chapters],
                "note": f"the plan played back, not a physics simulation; driving shown {DRIVE_X:g}x and arm work {ARM_X:g}x faster than planned"}
    except Exception as e:
        observe.emit("note", text=f"walkthrough failed: {type(e).__name__}: {e}")
        return None


# ------------------------------------------------------------------ the robot for the real-room tour (web/viewer/tour.html)

TOUR_FACES = 20000  # a mesh with more triangles than this is thinned to about this many for the browser


def _geom_mesh(m, g):
    """One visual geom as a trimesh in its body's frame, coloured, or None for a kind not drawn."""
    import trimesh

    t, size = int(m.geom_type[g]), m.geom_size[g]
    if t == mujoco.mjtGeom.mjGEOM_MESH:
        k = m.geom_dataid[g]
        v = m.mesh_vert[m.mesh_vertadr[k]: m.mesh_vertadr[k] + m.mesh_vertnum[k]].copy()
        f = m.mesh_face[m.mesh_faceadr[k]: m.mesh_faceadr[k] + m.mesh_facenum[k]].copy()
        mesh = trimesh.Trimesh(v, f, process=False)
        if len(f) > TOUR_FACES:
            try:
                mesh = mesh.simplify_quadric_decimation(face_count=TOUR_FACES)
            except Exception:
                pass  # no simplifier installed: keep the full mesh
    elif t == mujoco.mjtGeom.mjGEOM_BOX:
        mesh = trimesh.creation.box(extents=2 * size)
    elif t == mujoco.mjtGeom.mjGEOM_CYLINDER:
        mesh = trimesh.creation.cylinder(radius=size[0], height=2 * size[1], sections=24)
    elif t == mujoco.mjtGeom.mjGEOM_CAPSULE:
        mesh = trimesh.creation.capsule(radius=size[0], height=2 * size[1], count=[12, 12])
    elif t == mujoco.mjtGeom.mjGEOM_SPHERE:
        mesh = trimesh.creation.icosphere(radius=size[0], subdivisions=2)
    else:
        return None
    T = np.eye(4)
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, m.geom_quat[g])
    T[:3, :3], T[:3, 3] = R.reshape(3, 3), m.geom_pos[g]
    mesh.apply_transform(T)
    rgba = m.mat_rgba[m.geom_matid[g]] if m.geom_matid[g] >= 0 else m.geom_rgba[g]
    mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[float(c) for c in rgba[:3]] + [1.0], metallicFactor=0.15, roughnessFactor=0.6))
    return mesh


def tour_export(robot_xml: str, build: dict, route: dict, trajectory: dict) -> dict | None:
    """What the tour page needs to draw the robot inside the real scan: frames/tour_robot.glb (one node per
    body, meshes in the body's frame, metres, Z up) and frames/tour_frames.bin (float32, per film frame and
    per body: position x y z and quaternion w x y z in the world frame). Same timeline as walkthrough().
    Returns {"glb", "frames", "bodies", "fps", "n", "chapters"} or None."""
    where = observe.frame_path("tour")
    if where is None:
        return None
    try:
        import trimesh

        m = mujoco.MjModel.from_xml_string(robot_xml)
        d = mujoco.MjData(m)
        scene, bodies = trimesh.Scene(), []
        for b in range(1, m.nbody):
            geoms = [g for g in range(m.ngeom) if m.geom_bodyid[g] == b and m.geom_group[g] <= 2 and m.geom_rgba[g][3] > 0.05]
            meshes = [x for x in (_geom_mesh(m, g) for g in geoms) if x is not None]
            if not meshes:
                continue
            name = f"body{len(bodies)}"
            scene.graph.update(frame_to=name, frame_from=scene.graph.base_frame, matrix=np.eye(4))
            for i, mesh in enumerate(meshes):
                scene.add_geometry(mesh, node_name=f"{name}_g{i}", geom_name=f"{name}_g{i}", parent_node_name=name)
            bodies.append(b)
        glb = where[0].with_name("tour_robot.glb")
        glb.write_bytes(scene.export(file_type="glb"))
        frames, chapters = _timeline(build, route, trajectory)
        jadr = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j): m.jnt_qposadr[j] for j in range(m.njnt)}
        out = np.zeros((len(frames), len(bodies), 7), dtype=np.float32)
        for i, (pose, q) in enumerate(frames):
            mujoco.mj_resetData(m, d)
            for name, v in {**q, "joint_x": pose[0], "joint_y": pose[1], "joint_th": pose[2]}.items():
                if name in jadr:
                    d.qpos[jadr[name]] = v
            mujoco.mj_kinematics(m, d)
            out[i, :, :3], out[i, :, 3:] = d.xpos[bodies], d.xquat[bodies]
        where[0].with_name("tour_frames.bin").write_bytes(out.tobytes())
        return {"glb": "frames/tour_robot.glb", "frames": "frames/tour_frames.bin", "bodies": len(bodies), "fps": WALK_FPS, "n": len(frames),
                "chapters": [{"t": round(i / WALK_FPS, 1), "label": label} for i, label in chapters]}
    except Exception as e:
        observe.emit("note", text=f"tour export failed: {type(e).__name__}: {e}")
        return None
