"""The part cards in catalog/, as the composer reads them: loading, the valid combinations, price and mass.

Cards are read as files; nothing here imports another module of the pipeline.
"""
from __future__ import annotations

import functools
import itertools
import json
from pathlib import Path

import mujoco
import numpy as np

CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"
ASSETS = CATALOG_DIR / "_assets"
SLOTS = ("base", "lift", "arm", "gripper", "lidar")
PART_KEYS = ("base", "lift", "arm", "gripper", "lidar", "lidar_mount", "wrist_cam", "ego_cam")
SENSOR_DEFAULTS = {"lidar": "none", "lidar_mount": "base_front", "wrist_cam": False, "ego_cam": "none"}
CAMERA = "d435i"
# enumeration order inside a slot; cards not named here follow in file-name order
ORDER = {"base": ["tidybot_arx5", "tidybot_kinova", "tidybot_franka", "go2", "spot"],
         "lift": ["none", "liftkit_500", "liftkit_900", "liftkit_1400"],
         "arm": ["lite6", "xarm7", "ur5e"],
         "gripper": ["robotiq_2f85", "xarm_gripper", "lite6_gripper"],
         "lidar": ["none", "rplidar_s2", "vlp16"]}


@functools.lru_cache(maxsize=None)
def cards(slot: str) -> dict:
    """{id: card} for one folder of catalog/."""
    found = {}
    for p in sorted((CATALOG_DIR / slot).glob("*.json")):
        c = json.loads(p.read_text())
        found[c["id"]] = c
    first = [i for i in ORDER.get(slot, []) if i in found]
    return {i: found[i] for i in first + [i for i in found if i not in first]}


def card(slot: str, name: str) -> dict:
    return cards(slot)[name]


def camera() -> dict:
    return card("camera", CAMERA)


def asset(rel: str) -> Path:
    p = ASSETS / rel
    if not p.exists():
        raise FileNotFoundError(f"{p} is missing: run `python catalog/fetch_assets.py` to fill catalog/_assets")
    return p


def full(parts: dict) -> dict:
    """The eight keys, in order, with the sensor defaults filled in."""
    merged = {**SENSOR_DEFAULTS, **parts}
    return {k: merged.get(k) for k in PART_KEYS}


def key(parts: dict) -> tuple:
    p = full(parts)
    return tuple(p[k] for k in PART_KEYS)


def carrier_key(parts: dict) -> tuple:
    """What the arm's motion depends on: everything except the lidar and the ego camera."""
    p = full(parts)
    return (p["base"], p["lift"], p["arm"], p["gripper"], p["wrist_cam"])


def fits(arm: str, gripper: str) -> bool:
    a, g = card("arm", arm), card("gripper", gripper)
    if a.get("integrated_gripper"):
        return gripper == a["integrated_gripper"]
    return arm in g.get("fits_arms", []) and not g.get("integrated_in")


def validate(parts: dict) -> None:
    for slot in SLOTS:
        if parts.get(slot) not in cards(slot):
            raise ValueError(f"{slot} must be one of {list(cards(slot))}, not {parts.get(slot)!r}")
    if not fits(parts["arm"], parts["gripper"]):
        raise ValueError(f"gripper {parts['gripper']} does not fit arm {parts['arm']}")
    if parts["lidar_mount"] not in ("base_front", "stage_rear"):
        raise ValueError("lidar_mount must be base_front or stage_rear")
    if parts["ego_cam"] not in ("none", "base_front", "stage_front"):
        raise ValueError("ego_cam must be none, base_front or stage_front")
    if not isinstance(parts["wrist_cam"], bool):
        raise ValueError("wrist_cam must be true or false")
    if parts["lift"] == "none" and (parts["ego_cam"] == "stage_front"
                                    or (parts["lidar"] != "none" and parts["lidar_mount"] == "stage_rear")):
        raise ValueError("stage_* mounts need a lift")


def carriers():
    for b, l, a in itertools.product(cards("base"), cards("lift"), cards("arm")):
        for g in cards("gripper"):
            if fits(a, g):
                yield {"base": b, "lift": l, "arm": a, "gripper": g}


def sensor_sets(carrier: dict):
    has_lift = carrier["lift"] != "none"
    mounts = ("base_front", "stage_rear") if has_lift else ("base_front",)
    lidars = [("none", "base_front")] + [(n, mt) for n in cards("lidar") if n != "none" for mt in mounts]
    egos = ["none", "base_front"] + (["stage_front"] if has_lift else [])
    for (li, lm), w, e in itertools.product(lidars, (False, True), egos):
        yield {"lidar": li, "lidar_mount": lm, "wrist_cam": w, "ego_cam": e}


def candidates() -> list:
    return [full({**c, **s}) for c in carriers() for s in sensor_sets(c)]


def n_cameras(parts: dict) -> int:
    return int(bool(parts["wrist_cam"])) + int(parts["ego_cam"] != "none")


def price(parts: dict) -> int:
    parts = full(parts)
    return sum(card(s, parts[s])["price_usd"] for s in SLOTS) + n_cameras(parts) * camera()["price_usd"]


@functools.lru_cache(maxsize=None)
def model_mass(rel: str) -> float:
    return float(mujoco.MjModel.from_xml_path(str(asset(rel))).body_mass.sum())


def part_mass(parts: dict) -> float:
    """Sum of the parts' masses: card figures for the stand-ins, the simulator model's own mass otherwise.
    The composed model must weigh exactly this (asserted in model.Robot)."""
    parts = full(parts)
    a, g = card("arm", parts["arm"]), card("gripper", parts["gripper"])
    return (base_info(parts["base"])["mass_kg"] + card("lift", parts["lift"])["mass_kg"] + model_mass(a["model"])
            + (model_mass(g["model"]) if "model" in g else 0.0)
            + card("lidar", parts["lidar"])["mass_kg"] + n_cameras(parts) * model_mass(camera()["model"]))


def _chain_length(rel: str, site: str) -> float:
    """Sum of the link offsets from a model's root to one of its sites: no pose puts the site farther
    from the root than this."""
    m = mujoco.MjModel.from_xml_path(str(asset(rel)))
    sid = m.site(site).id
    total, b = float(np.linalg.norm(m.site_pos[sid])), int(m.site_bodyid[sid])
    while b > 0:
        total += float(np.linalg.norm(m.body_pos[b]))
        b = int(m.body_parentid[b])
    return total


@functools.lru_cache(maxsize=None)
def arm_span(arm: str, gripper: str) -> float:
    """An upper bound on how far the tool point can be from the arm's mount, from the models' link lengths."""
    a, g = card("arm", arm), card("gripper", gripper)
    if a.get("integrated_gripper"):
        return _chain_length(a["model"], a["tool_site"])
    tip = _chain_length(g["model"], g["tool_site"]) if "tool_site" in g else g["tool_offset_m"]
    return _chain_length(a["model"], a["flange_site"]) + tip


# ------------------------------------------------------------------------------- base geometry


def corners(m):
    """The eight corners of every geom's bounding box, in the geom's frame: (ngeom, 8, 3)."""
    c = np.array(list(itertools.product([-1, 1], repeat=3)), dtype=float)
    return m.geom_aabb[:, :3][:, None, :] + c[None] * m.geom_aabb[:, 3:][:, None, :]


def world_points(m, d, mask=None):
    R = d.geom_xmat.reshape(-1, 3, 3)
    pts = np.einsum("gij,gkj->gki", R, corners(m)) + d.geom_xpos[:, None, :]
    return pts if mask is None else pts[mask]


@functools.lru_cache(maxsize=None)
def base_info(name: str) -> dict:
    """A base card plus what the composer derives from it, all in the base frame (x forward, z up, origin
    on the floor under the base centre): outline_m, mass_kg, support (rectangle), mounts top and front,
    and for a legged base its standing height and the leg joints' standing values."""
    B = dict(card("base", name))
    if B["kind"] == "wheeled":
        x, y, inset = B["outline_m"]["x"], B["outline_m"]["y"], B["support_inset_m"]
        B["support"] = {"x": [x[0] + inset, x[1] - inset], "y": [y[0] + inset, y[1] - inset]}
        return B
    m = mujoco.MjModel.from_xml_path(str(asset(B["model"])))
    d = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d, m.key(B["keyframe"]).id)
    d.qpos[:2] = 0
    d.qpos[3:7] = [1, 0, 0, 0]
    mujoco.mj_forward(m, d)
    pts = world_points(m, d)
    zmin = pts[..., 2].min()
    allp = pts.reshape(-1, 3)
    feet = np.array([d.geom_xpos[g][:2] for g in range(m.ngeom) if pts[g][:, 2].min() < zmin + 0.03 and m.geom_contype[g]])
    trunk = world_points(m, d, m.geom_bodyid == 1).reshape(-1, 3)
    top = float(trunk[:, 2].max() - zmin)
    B.update(
        mass_kg=float(m.body_mass.sum()), stand_m=float(d.qpos[2] - zmin),
        outline_m={"x": [float(allp[:, 0].min()), float(allp[:, 0].max())],
                   "y": [float(allp[:, 1].min()), float(allp[:, 1].max())], "z": [0.0, top]},
        support={"x": [float(feet[:, 0].min()), float(feet[:, 0].max())], "y": [float(feet[:, 1].min()), float(feet[:, 1].max())]},
        mounts={"top": [0.0, 0.0, top], "front": [float(trunk[:, 0].max()) - B["front_inset_m"], 0.0, top]},
        home={m.joint(j).name: float(d.qpos[m.jnt_qposadr[j]]) for j in range(1, m.njnt)})
    return B


def rect(xr, yr) -> list:
    return [[xr[0], yr[0]], [xr[1], yr[0]], [xr[1], yr[1]], [xr[0], yr[1]]]
