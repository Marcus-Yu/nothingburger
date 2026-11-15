"""The real model of a robot, for the web app: the composed MuJoCo model's meshes as one GLB.

    robot_glb(parts) -> bytes      # cached in catalog/_cache/glb/

The composer builds every candidate from the vendors' models (MuJoCo Menagerie, the TidyBot++ CAD), so what
the checks measure is also what can be shown. The GLB has one node per body, named `<stage>/<n>` with the stage
the design pages assemble by: body (the base), torso (the lift), arm, hand (the gripper), sensors. Meshes sit in
world coordinates in the stowed pose (metres, Z up), thinned (to a quarter of their triangles where that keeps the shape) so a robot is a
few megabytes, not the 20 MB of the full meshes. It is for looking at; nothing is measured on it.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import mujoco
import numpy as np

from . import composer

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "catalog" / "_cache" / "glb"
VERSION = 3          # bump to drop cached files when the export changes
THIN_OVER = 4000     # a mesh with more faces than this is thinned
THIN_TO = (0.25, 0.5)  # to this share of its faces (the first that keeps its shape), but not below THIN_MIN
THIN_MIN = 2500
THIN_KEEPS = 0.85    # a thinned mesh must keep this share of the surface area, or the full mesh is used
SMALL_M = 0.12       # a part smaller than this across (a camera, a lidar) is thinned to SMALL_TO whatever it loses:
SMALL_TO = 0.1       # its faces are mostly inside it or too fine to see at the size a robot is drawn
SMALL_MIN = 1500
STAGES = (("arm/", "arm"), ("grip/", "hand"), ("sens/", "sensors"), ("lift", "torso"))


def stage_of(body_name: str) -> str:
    for prefix, stage in STAGES:
        if body_name.startswith(prefix):
            return stage
    return "body"


_THINNED: dict = {}   # each vendor mesh once it is thinned, for as long as the process lives: most robots share most parts


def _thin(v, f):
    """The mesh with these vertices and faces, welded and thinned. Kept in memory, so only the first robot
    with a part pays for it (about a second a robot otherwise; a tenth of that with every part seen before)."""
    import trimesh

    key = (len(v), len(f), hashlib.blake2b(v.tobytes(), digest_size=16).hexdigest())
    if key in _THINNED:
        return _THINNED[key].copy()
    mesh = trimesh.Trimesh(v, f, process=False)
    # Many vendor meshes carry three vertices of their own per triangle (for hard edges). Thinning such a
    # mesh tears it into shards, so the vertices are welded first; the page works the edges out again.
    mesh.merge_vertices(digits_vertex=6)
    small = float(np.linalg.norm(np.ptp(v, axis=0))) < SMALL_M
    if len(f) > THIN_OVER:
        try:
            for share in ((SMALL_TO,) if small else THIN_TO):
                want = max(SMALL_MIN if small else THIN_MIN, int(len(f) * share))
                if want >= len(mesh.faces):
                    break
                thin = mesh.simplify_quadric_decimation(face_count=want)
                if small or thin.area >= THIN_KEEPS * mesh.area:
                    mesh = thin
                    break
        except Exception:
            pass  # no simplifier installed: keep the full mesh
    _THINNED[key] = mesh
    return mesh.copy()


def _mesh(m, g):
    """One visual geom as a trimesh in its body's frame, coloured, or None for a kind not drawn."""
    import trimesh

    t, size = int(m.geom_type[g]), m.geom_size[g]
    if t == mujoco.mjtGeom.mjGEOM_MESH:
        k = m.geom_dataid[g]
        mesh = _thin(m.mesh_vert[m.mesh_vertadr[k]: m.mesh_vertadr[k] + m.mesh_vertnum[k]].copy(),
                     m.mesh_face[m.mesh_faceadr[k]: m.mesh_faceadr[k] + m.mesh_facenum[k]].copy())
    elif t == mujoco.mjtGeom.mjGEOM_BOX:
        mesh = trimesh.creation.box(extents=2 * size)
    elif t == mujoco.mjtGeom.mjGEOM_CYLINDER:
        mesh = trimesh.creation.cylinder(radius=size[0], height=2 * size[1], sections=24)
    elif t == mujoco.mjtGeom.mjGEOM_CAPSULE:
        mesh = trimesh.creation.capsule(radius=size[0], height=2 * size[1], count=[10, 10])
    elif t == mujoco.mjtGeom.mjGEOM_SPHERE:
        mesh = trimesh.creation.icosphere(radius=size[0], subdivisions=2)
    else:
        return None
    rgba = m.mat_rgba[m.geom_matid[g]] if m.geom_matid[g] >= 0 else m.geom_rgba[g]
    mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[float(c) for c in rgba[:3]] + [1.0], metallicFactor=0.2, roughnessFactor=0.55))
    return mesh


def _build_glb(parts: dict) -> bytes:
    import trimesh

    made = composer.compose({"parts": parts, "checks": []})
    m = mujoco.MjModel.from_xml_string(made["robot_xml"])
    d = mujoco.MjData(m)
    for name, value in (made["build"]["stowed"].get("qpos") or {}).items():  # the pose the checks fold it to
        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
        if j >= 0 and m.jnt_type[j] in (mujoco.mjtJoint.mjJNT_HINGE, mujoco.mjtJoint.mjJNT_SLIDE):
            d.qpos[m.jnt_qposadr[j]] = value
    mujoco.mj_forward(m, d)
    scene = trimesh.Scene()
    counts: dict = {}
    for b in range(1, m.nbody):
        geoms = [g for g in range(m.ngeom) if m.geom_bodyid[g] == b and m.geom_group[g] <= 2 and m.geom_rgba[g][3] > 0.05]
        stage = stage_of(m.body(b).name)
        for g in geoms:
            mesh = _mesh(m, g)
            if mesh is None:
                continue
            T = np.eye(4)   # the geom's pose in the world, in this pose
            T[:3, :3], T[:3, 3] = d.geom_xmat[g].reshape(3, 3), d.geom_xpos[g]
            mesh.apply_transform(T)
            n = counts[stage] = counts.get(stage, 0) + 1
            scene.add_geometry(mesh, node_name=f"{stage}/{n}", geom_name=f"{stage}/{n}")
    return scene.export(file_type="glb")


def _key(parts: dict) -> str:
    cards = sorted((f.name, f.stat().st_mtime_ns) for f in (REPO / "catalog").glob("*/*.json"))
    raw = json.dumps([VERSION, {k: parts.get(k) for k in sorted(parts)}, cards], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


DEFAULTS = {"lift": "none", "lidar": "none", "lidar_mount": "base_front", "wrist_cam": False, "ego_cam": "base_front"}


def robot_glb(parts: dict) -> bytes:
    """The GLB for these parts (the eight keys of design.json's `parts`; the sensors and lift may be left
    out), from the cache when it is there. Raises ValueError for parts that are not in the catalog."""
    parts = {**DEFAULTS, **{k: v for k, v in parts.items() if v is not None}}
    for slot in ("base", "arm", "gripper"):
        if not parts.get(slot):
            raise ValueError(f"a robot needs a {slot}")
    f = CACHE / f"{_key(parts)}.glb"
    try:
        return f.read_bytes()
    except OSError:
        pass
    try:
        data = _build_glb(parts)
    except (KeyError, FileNotFoundError) as e:
        raise ValueError(f"these parts cannot be composed: {e}") from e
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, f)
    except OSError:
        pass
    return data
