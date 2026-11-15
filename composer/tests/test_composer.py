import copy
import json
import re
from pathlib import Path

import jsonschema
import mujoco
import pytest

import composer.api as api

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
ASSETS = Path(__file__).resolve().parents[2] / "catalog" / "_assets"
GOOD = {"base": "tidybot_arx5", "lift": "liftkit_500", "arm": "xarm7", "gripper": "xarm_gripper",
        "lidar": "rplidar_s2", "lidar_mount": "stage_rear", "wrist_cam": True, "ego_cam": "stage_front"}
LEGGED = {"base": "go2", "lift": "none", "arm": "lite6", "gripper": "lite6_gripper",
          "lidar": "vlp16", "lidar_mount": "base_front", "wrist_cam": True, "ego_cam": "base_front"}
BAD = {"base": "go2", "lift": "none", "arm": "lite6", "gripper": "lite6_gripper",
       "lidar": "none", "lidar_mount": "base_front", "wrist_cam": False, "ego_cam": "none"}


def schema(kind):
    return json.loads((CONTRACTS / f"{kind}.schema.json").read_text())


def status(result, check, task=None):
    hits = [c for c in result["checks"] if c["check"] == check and c.get("task") == task]
    assert len(hits) == 1, f"{check}/{task}: {len(hits)} results"
    return hits[0]["status"]


def with_values(requirements, **values):
    r = copy.deepcopy(requirements)
    for row in r["requirements"]:
        if row["id"] in values:
            row.update(values[row["id"]] if isinstance(values[row["id"]], dict) else {"value": values[row["id"]]})
    return r


@pytest.fixture(scope="session")
def requirements():
    return json.loads((CONTRACTS / "requirements.example.json").read_text())


@pytest.fixture(scope="session")
def designed(requirements):
    return api.design(requirements)


def test_candidates_are_every_valid_combination():
    cands = api.candidates()
    assert len(cands) == 7140  # 5 bases x 4 lifts x 14 arm-and-gripper pairs x the sensor sets
    assert all(list(c) == ["base", "lift", "arm", "gripper", "lidar", "lidar_mount", "wrist_cam", "ego_cam"] for c in cands)
    assert GOOD in cands and BAD in cands
    assert not any(c["lift"] == "none" and (c["ego_cam"] == "stage_front" or c["lidar_mount"] == "stage_rear") for c in cands)
    assert all((c["arm"] == "lite6") == (c["gripper"] == "lite6_gripper") for c in cands)
    assert all((c["arm"] == a) == (c["gripper"] == g) for c in cands
               for a, g in (("piper", "piper_gripper"), ("vx300s", "vx300s_gripper"), ("z1", "z1_gripper")))
    assert {c["gripper"] for c in cands if c["arm"] == "fr3"} == {"robotiq_2f85", "franka_hand"}


@pytest.mark.parametrize("parts", [GOOD, LEGGED], ids=["wheeled", "legged"])
def test_compose_loads_in_mujoco_and_build_fits_the_contract(parts):
    out = api.compose({"schema": "design/1", "parts": parts})
    xml, build = out["robot_xml"], out["build"]
    model = mujoco.MjModel.from_xml_string(xml)  # absolute mesh paths: loads from a string, from any directory
    files = re.findall(r'file="([^"]+)"', xml)  # every mesh comes from the repo's own catalog/_assets
    assert files and all(Path(f).is_absolute() and ASSETS in Path(f).parents for f in files)
    jsonschema.validate(build, schema("build"))
    assert build["parts"] == parts
    assert abs(float(model.body_mass.sum()) - build["mass_kg"]) < 0.01

    def has(kind, name):
        return mujoco.mj_name2id(model, kind, name) >= 0

    assert [j["name"] for j in build["joints"]] == [model.joint(j).name for j in range(model.njnt)]
    assert set(build["arm_joints"]) <= {j["name"] for j in build["joints"]}
    assert set(build["stowed"]["qpos"]) <= {j["name"] for j in build["joints"]}
    assert has(mujoco.mjtObj.mjOBJ_SITE, build["tool_site"])
    assert {s["site"] for s in build["sensors"]} == {"lidar", "ego", "wrist"}
    assert all(has(mujoco.mjtObj.mjOBJ_SITE, s["site"]) for s in build["sensors"])
    assert has(mujoco.mjtObj.mjOBJ_KEY, build["stowed"]["keyframe"])
    assert build["base"]["inscribed_radius_m"] < build["base"]["circumscribed_radius_m"]
    assert {r["tool_axis"] for r in build["reach_envelope"]} == {"up", "down", "side"}
    assert all(0 <= r["min_distance_m"] <= r["max_distance_m"] for r in build["reach_envelope"])
    # the stowed keyframe reproduces the stowed height
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("stowed").id)
    mujoco.mj_forward(model, data)
    tool_z = data.site_xpos[model.site("tool").id][2]
    assert 0 < tool_z <= build["stowed"]["height_m"] + 1e-6
    if parts is LEGGED:
        # a quadruped sidesteps and turns in place, so it is planned as holonomic (assumed in its card)
        assert build["base"]["kind"] == "legged" and build["base"]["holonomic"]
        assert any(k.startswith("base/") for k in build["stowed"]["qpos"])


def test_check_known_good(requirements):
    r = api.check(GOOD, requirements)
    assert r["feasible"] and r["parts"] == GOOD and r["price_usd"] == 23800
    for c in r["checks"]:
        jsonschema.validate(c, schema("check"))
        assert c["status"] in ("pass", "not_assessable")
    for check in ("doorway", "turn", "door header", "steps", "base payload", "lidar present", "lidar view",
                  "wrist camera", "ego camera"):
        assert status(r, check) == "pass"
    for check in ("reach", "tip-over", "payload", "opening", "force", "twist"):
        assert status(r, check, "t1") == "pass"
    assert status(r, "press", "t2") == "not_assessable"   # press force is assumed
    assert status(r, "force", "t3") == "not_assessable"   # no band in the ledger for the bag
    assert status(r, "tip-over", "t2") == "pass" and status(r, "tip-over", "t3") == "pass"
    assert any(label.startswith("press not verified") for label in r["labels"])
    by = {(c["check"], c.get("task")): c for c in r["checks"]}
    assert by[("doorway", None)]["requirements"] == ["r_width"] and by[("doorway", None)]["limit"] == 0.61
    assert by[("force", "t1")]["requirements"] == ["r_t1_force"]


def test_check_known_bad(requirements):
    r = api.check(BAD, requirements)
    assert not r["feasible"]
    assert status(r, "lidar present") == "fail"
    assert status(r, "wrist camera") == "fail"
    assert status(r, "ego camera") == "fail"
    assert status(r, "reach", "t1") == "fail"      # a 2.24 m bulb from an arm on a dog's back
    assert status(r, "opening", "t1") == "fail"    # 16 mm stroke against 70 mm
    assert status(r, "force", "t1") == "fail"      # open/close only
    assert status(r, "steps") == "pass"
    assert all(c["status"] != "not_run" for c in r["checks"])


def test_force_gate_and_gripper_range(requirements):
    robotiq = {**GOOD, "gripper": "robotiq_2f85"}
    assert status(api.check(robotiq, requirements), "force", "t1") == "fail"  # 20 N minimum, band tops out at 18 N
    travel = with_values(requirements, r_t1_force={"grip_source": "travel"})
    r = api.check(robotiq, travel)
    assert status(r, "force", "t1") == "not_assessable" and r["feasible"]


def test_step_needs_a_climbing_base_and_a_3d_lidar(requirements):
    r = api.check(GOOD, with_values(requirements, r_step=0.12))
    assert status(r, "steps") == "fail" and status(r, "lidar present") == "fail"
    assert status(api.check(LEGGED, with_values(requirements, r_step=0.12)), "steps") == "pass"


def test_design_picks_the_cheapest_feasible(requirements, designed):
    jsonschema.validate(designed, schema("design"))
    assert designed["parts"] is not None and designed["considered"] == 7140
    assert {k: designed["parts"][k] for k in ("base", "lift", "arm", "gripper", "lidar", "wrist_cam")} == {
        "base": "tidybot_arx5", "lift": "liftkit_500", "arm": "xarm7", "gripper": "xarm_gripper", "lidar": "rplidar_s2",
        "wrist_cam": True}
    assert designed["price_usd"] == 23800
    again = api.check(designed["parts"], requirements)
    assert again["feasible"] and again["checks"] == designed["checks"]
    assert api.compose(designed)["build"]["stowed"] == api.compose(designed, requirements=requirements)["build"]["stowed"]
    out = api.compose(designed)
    jsonschema.validate(out["build"], schema("build"))
    mujoco.MjModel.from_xml_string(out["robot_xml"])
    doorway = next(c for c in designed["checks"] if c["check"] == "doorway")
    header = next(c for c in designed["checks"] if c["check"] == "door header")
    assert out["build"]["stowed"]["width_m"] == doorway["value"] <= 0.61
    assert out["build"]["stowed"]["height_m"] == header["value"] <= 1.98


def test_design_reports_binding_checks_when_nothing_passes(requirements):
    d = api.design(with_values(requirements, r_width=0.30))
    assert d["parts"] is None
    binding = d["infeasible"]["binding_checks"]
    assert binding and all(c["status"] == "fail" for c in binding)
    assert "doorway" in {c["check"] for c in binding}
    assert binding[0]["requirements"] == ["r_width"]


def deep_counter(requirements, per_target: bool):
    """The example ledger plus a wipe over a counter 0.6 m deep (t2): two strokes, ends 0.05 m and 0.55 m in
    from the counter's front edge at x = 6.4. A 0.2 m disc gets its edge 0.05 m from the near ends, 0.326 m
    from the counter's centre (the task's free_floor row) and 0.55 m from the far ends."""
    r = copy.deepcopy(requirements)
    pts = [([6.45, 1.4, 0.92], 0.05), ([6.95, 1.4, 0.92], 0.55), ([6.95, 1.55, 0.92], 0.55), ([6.45, 1.55, 0.92], 0.05)]
    targets = [{"point": p, "tool_axis": [0, 0, -1], "held_axes": ["position", "tool_axis"],
                **({"edge_distance_m": e, "side": [-1.0, 0.0]} if per_target else {})} for p, e in pts]
    r["requirements"] += [
        {"id": "r_t2_reach", "task": "t2", "quantity": "reach_targets", "value": targets, "unit": "pose", "tolerance": 0.01,
         "source": "assumed"},
        {"id": "r_t2_floor", "task": "t2", "quantity": "free_floor", "value": {"edge_distance_m": 0.326, "side": [-1.0, 0.0]},
         "unit": "m", "tolerance": 0.05, "source": "scan"}]
    return r


def test_reach_is_checked_per_target_on_a_deep_counter(requirements):
    by = lambda r, check: next(c for c in r["checks"] if c["check"] == check and c.get("task") == "t2")
    # the anchor's free floor alone (the old check): the xarm7 passes, though it cannot get to the far stroke ends
    old = api.check(GOOD, deep_counter(requirements, per_target=False))
    assert by(old, "reach")["status"] == "pass" and old["feasible"]
    assert [t["needed_m"] for t in by(old, "reach")["targets"]] == [0.53] * 4      # 0.326 + half the base, for every target
    # each target's own free floor: the far ends need the base centre 0.754 m away, the arm stops near 0.70 m
    new = api.check(GOOD, deep_counter(requirements, per_target=True))
    reach = by(new, "reach")
    jsonschema.validate(reach, schema("check"))
    assert reach["status"] == "fail" and not new["feasible"]
    assert reach["target"] == 1 and "target 1 at 0.92 m" in reach["why"] and "[1, 2]" in reach["why"]
    assert reach["limit"] == 0.754 and reach["value"] < reach["limit"] - 0.05      # needed distance, envelope's limit
    assert [t["status"] for t in reach["targets"]] == ["pass", "fail", "fail", "pass"]
    assert [t["needed_m"] for t in reach["targets"]] == [0.254, 0.754, 0.754, 0.254]
    assert "target 0" in by(new, "tip-over")["why"] or "target 3" in by(new, "tip-over")["why"]  # only reachable ends are posed
    # a longer arm reaches the far ends, and tip-over is then taken at each target's own distance
    long_arm = api.check({**GOOD, "arm": "ur5e"}, deep_counter(requirements, per_target=True))
    assert by(long_arm, "reach")["status"] == "pass" and by(long_arm, "reach")["target"] in (1, 2)
    assert by(long_arm, "tip-over")["status"] == "pass" and "0.80 m out" in by(long_arm, "tip-over")["why"]
    # design agrees: with the per-target numbers the cheapest robot is no longer the xarm7
    assert api.design(deep_counter(requirements, per_target=False))["parts"]["arm"] == "xarm7"
    picked = api.design(deep_counter(requirements, per_target=True))
    assert picked["parts"]["arm"] != "xarm7" and picked["price_usd"] > 23800
