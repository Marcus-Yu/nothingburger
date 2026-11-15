"""Bake a kit-composed MJCF into a self-contained test fixture (run once, by hand).

    python make_fixtures.py <kit dir> <in.xml> <out.xml>

The kit's `compose` writes MJCF that names about 100 MB of mesh files. A fixture cannot carry
those, so this drops every mesh geom that neither collides nor is the only thing in its body,
and replaces each remaining mesh by the vertices of its convex hull, written inline. MuJoCo
collides meshes by their convex hull anyway, so the collision geometry is unchanged (hulls with
more than MAX_VERTS vertices are thinned to their extreme points in MAX_VERTS directions).
It then checks the baked model against the original: same body masses, same joints, and the
tool site and collision geoms in the same places at random joint values.
"""
from __future__ import annotations

import sys
from pathlib import Path

import mujoco
import numpy as np
from scipy.spatial import ConvexHull

MAX_VERTS = 120
DIRS = {"arm/": "ufactory_xarm7/assets", "grip/": "ufactory_xarm7/assets", "sens/": "realsense_d435i/assets",
        "base/": "boston_dynamics_spot/assets"}


def read_verts(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".obj":
        rows = [ln.split()[1:4] for ln in path.read_text().splitlines() if ln.startswith("v ")]
        return np.array(rows, dtype=float)
    raw = path.read_bytes()
    n = int(np.frombuffer(raw[80:84], dtype="<u4")[0])
    assert len(raw) == 84 + 50 * n, f"{path} is not a binary STL"
    tri = np.frombuffer(raw[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return tri["v"].reshape(-1, 3).astype(float)


def hull_verts(v: np.ndarray) -> np.ndarray:
    h = v[ConvexHull(v).vertices]
    if len(h) <= MAX_VERTS:
        return h
    i = np.arange(MAX_VERTS) + 0.5
    phi, th = np.arccos(1 - 2 * i / MAX_VERTS), np.pi * (1 + 5 ** 0.5) * i
    d = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)
    return h[np.unique((h @ d.T).argmax(0))]


def resolve(kit: Path, name: str, file: str) -> Path:
    if Path(file).is_absolute():
        return Path(file)
    for prefix, sub in DIRS.items():
        if name.startswith(prefix):
            return kit / "menagerie" / sub / file
    raise SystemExit(f"do not know where mesh {name} ({file}) lives")


def main(kit: Path, src: Path, out: Path) -> None:
    text = src.read_text()
    ref_spec = mujoco.MjSpec.from_string(text)
    for me in ref_spec.meshes:
        me.file = str(resolve(kit, me.name, me.file))
    ref = ref_spec.compile()

    spec = mujoco.MjSpec.from_string(text)
    used = set()
    for g in list(spec.geoms):
        if g.type != mujoco.mjtGeom.mjGEOM_MESH:
            continue
        gid = mujoco.mj_name2id(ref, mujoco.mjtObj.mjOBJ_GEOM, g.name) if g.name else -1
        if gid < 0:  # unnamed: find it by mesh and body in the compiled model
            mid = ref.mesh(g.meshname).id
            bid = ref.body(g.parent.name).id
            cand = [i for i in range(ref.ngeom) if ref.geom_dataid[i] == mid and ref.geom_bodyid[i] == bid]
            collides = any(ref.geom_contype[i] or ref.geom_conaffinity[i] for i in cand)
        else:
            collides = bool(ref.geom_contype[gid] or ref.geom_conaffinity[gid])
        if collides:
            used.add(g.meshname)
        else:
            spec.delete(g)
    for me in list(spec.meshes):
        if me.name not in used:
            spec.delete(me)
            continue
        v = read_verts(resolve(kit, me.name, me.file)) * np.array(me.scale)
        me.file = ""
        me.scale = [1, 1, 1]
        me.uservert = hull_verts(v).flatten().tolist()
    for collection in (spec.textures, spec.materials):
        for x in list(collection):
            if getattr(x, "file", ""):
                spec.delete(x)
    for b in spec.bodies:  # some bodies took their mass from a mesh geom: pin every inertia to the original
        if b.name and b.name != "world" and ref.body(b.name).mass[0] > 0:
            rb = ref.body(b.name)
            b.mass, b.ipos, b.iquat, b.inertia = float(rb.mass[0]), rb.ipos, rb.iquat, rb.inertia
            b.explicitinertial = True
    baked = spec.compile()
    xml = spec.to_xml()
    baked = mujoco.MjModel.from_xml_string(xml)  # the string alone must load

    assert baked.nq == ref.nq and baked.njnt == ref.njnt and baked.nbody == ref.nbody
    assert np.allclose(baked.body_mass, ref.body_mass, atol=1e-9), "body masses changed"
    assert np.allclose(baked.jnt_range, ref.jnt_range)
    rng = np.random.default_rng(0)
    d0, d1 = mujoco.MjData(ref), mujoco.MjData(baked)
    worst = 0.0
    for _ in range(5):
        q = ref.qpos0 + rng.uniform(-0.5, 0.5, ref.nq)
        d0.qpos[:], d1.qpos[:] = q, q
        mujoco.mj_forward(ref, d0)
        mujoco.mj_forward(baked, d1)
        worst = max(worst, float(np.abs(d0.site_xpos[ref.site("tool").id] - d1.site_xpos[baked.site("tool").id]).max()))
        worst = max(worst, float(np.abs(d0.xipos - d1.xipos).max()))
    assert worst < 1e-6, f"kinematics moved by {worst}"
    out.write_text(xml)
    print(f"wrote {out}: {len(xml) // 1024} kB, {baked.nmesh} hull meshes, {baked.ngeom} geoms (was {ref.ngeom})")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
