import math

import jsonschema
import numpy as np
import pytest

from motion import api
from motion.ik import Arm

from .conftest import reqs, target

STANDOFF = {"task": "t1", "pose": [2.0, 3.0, 0.0], "task_yaw_rad": 0.0, "reach_ok": True, "spares": []}
BULB = target([2.0, 3.0, 2.24], [0, 0, 1])


def wrap(entry, build):
    return {"schema": "trajectory/1", "robot": "robot.xml", "joints": build["arm_joints"], "tasks": [entry],
            "failures": [entry["failure"]] if "failure" in entry else []}


def check_entry(entry, xml, build, schema):
    """What every good entry has: the schema, three phases in order, unbroken time, samples inside
    the joint limits and clear of the robot, starting and ending stowed."""
    jsonschema.validate(wrap(entry, build), schema)
    assert "failure" not in entry, entry.get("failure")
    assert [s["phase"] for s in entry["segments"]] == ["approach", "work", "retreat"]
    assert entry["collisions"] == 0 and entry["max_position_error_m"] <= 0.01
    arm = Arm(xml, build)
    arm.set_base(entry["standoff"])
    t_prev, q_prev = None, None
    for seg in entry["segments"]:
        first = seg["samples"][0]
        if t_prev is not None:  # each segment starts where the last one ended
            assert first["t"] == t_prev and first["q"] == q_prev
        for a, b in zip(seg["samples"], seg["samples"][1:]):
            assert b["t"] == pytest.approx(a["t"] + 0.05, abs=2e-3)
        for s in seg["samples"]:
            q = np.array(s["q"])
            assert len(q) == len(build["arm_joints"]) and arm.within(q)
        for s in seg["samples"][::5]:
            arm.set(np.array(s["q"]))
            assert not arm.collides()
        t_prev, q_prev = seg["samples"][-1]["t"], seg["samples"][-1]["q"]
    stowed = [round(float(v), 5) for v in arm.q_stowed]
    assert entry["segments"][0]["samples"][0]["q"] == stowed and q_prev == stowed
    return arm


def tool_at(arm, q):
    arm.set(np.array(q))
    return arm.tool_pos(), arm.tool_axis()


def test_twist_with_the_models_roll_range(wheeled_xml, wheeled_build, trajectory_schema):
    task = {"id": "t1", "skill": "twist_out"}
    e = api.retarget(None, wheeled_xml, build=wheeled_build, task=task, standoff=STANDOFF,
                     requirements=reqs("t1", [BULB], wrist_roll_turns=3.0))
    arm = check_entry(e, wheeled_xml, wheeled_build, trajectory_schema)
    work = e["segments"][1]
    assert work["kind"] == "twist" and work["turns"] == 3.0
    assert work["regrasps"] == 1  # the roll joint spans two turns, so three turns take two strokes
    # the approach passes the pre-approach point 0.10 m below the bulb and ends at it
    p_end, z_end = tool_at(arm, e["segments"][0]["samples"][-1]["q"])
    assert np.linalg.norm(p_end - BULB["point"]) < 0.01 and z_end[2] > math.cos(math.radians(10))
    p_pre, _ = tool_at(arm, e["segments"][0]["samples"][-21]["q"])
    assert np.linalg.norm(p_pre - (np.array(BULB["point"]) - [0, 0, 0.10])) < 0.01
    # through the whole twist the tool stays on the bulb, and only the roll joint moves
    qs = np.array([s["q"] for s in work["samples"]])
    assert np.allclose(qs[:, :-1], qs[0, :-1], atol=1e-3)
    for q in qs[::25]:
        p, z = tool_at(arm, q)
        assert np.linalg.norm(p - BULB["point"]) < 0.01 and z[2] > math.cos(math.radians(10))
    # roll done while the gripper is closed adds up to the turns asked for, all in one direction
    grip, closed_roll, events = "open", 0.0, list(work["events"])
    for a, b in zip(work["samples"], work["samples"][1:]):
        while events and events[0]["t"] <= a["t"] + 1e-9:
            grip = events.pop(0)["gripper"]
        if grip == "close":
            closed_roll += b["q"][-1] - a["q"][-1]
    assert abs(closed_roll) == pytest.approx(3.0 * 2 * math.pi, abs=1e-3)
    assert [ev["gripper"] for ev in work["events"]] == ["close", "open", "close"]


@pytest.mark.parametrize("skill,span,turns", [("twist_out", math.pi, 3.0), ("twist_in", 2.5, 1.5), ("twist_in", 7.0, 0.5)])
def test_twist_regrasps_follow_the_roll_range(wheeled_xml, wheeled_build, trajectory_schema, skill, span, turns):
    wheeled_build["joints"].append({"name": "arm/joint7", "type": "hinge", "range": [-span / 2, span / 2]})
    e = api.retarget(None, wheeled_xml, build=wheeled_build, task={"id": "t1", "skill": skill}, standoff=STANDOFF,
                     requirements=reqs("t1", [BULB], wrist_roll_turns=turns))
    check_entry(e, wheeled_xml, wheeled_build, trajectory_schema)
    work = e["segments"][1]
    strokes = math.ceil(turns * 2 * math.pi / span - 1e-9)
    assert work["regrasps"] == strokes - 1
    assert sum(ev["gripper"] == "close" for ev in work["events"]) == strokes
    roll = [s["q"][-1] for s in work["samples"]]
    assert min(roll) >= -span / 2 - 1e-6 and max(roll) <= span / 2 + 1e-6


def test_twist_in_and_out_turn_opposite_ways(wheeled_xml, wheeled_build):
    ends = {}
    for skill in ("twist_in", "twist_out"):
        e = api.retarget(None, wheeled_xml, build=wheeled_build, task={"id": "t1", "skill": skill}, standoff=STANDOFF,
                         requirements=reqs("t1", [BULB], wrist_roll_turns=1.0))
        work = e["segments"][1]
        close_t = work["events"][0]["t"]
        at_close = next(s for s in work["samples"] if s["t"] >= close_t)
        ends[skill] = work["samples"][-1]["q"][-1] - at_close["q"][-1]
    assert ends["twist_in"] == pytest.approx(-ends["twist_out"]) and abs(ends["twist_in"]) == pytest.approx(2 * math.pi, abs=1e-3)


def test_two_stroke_wipe(wheeled_xml, wheeled_build, trajectory_schema):
    pts = [[2.5, 2.8, 0.9], [2.5, 3.2, 0.9], [2.6, 2.8, 0.9]]
    e = api.retarget(None, wheeled_xml, build=wheeled_build, task={"id": "t2", "skill": "wipe"}, standoff=STANDOFF,
                     requirements=reqs("t2", [target(p, [0, 0, -1]) for p in pts], press_force=10.0))
    arm = check_entry(e, wheeled_xml, wheeled_build, trajectory_schema)
    work = e["segments"][1]
    assert work["kind"] == "wipe" and work["strokes"] == 2 and work["press_force_n"] == 10.0
    tool = [tool_at(arm, s["q"]) for s in work["samples"]]
    path = np.array([p for p, _ in tool])
    assert np.allclose(path[0], pts[0], atol=0.01) and np.allclose(path[-1], pts[2], atol=0.01)
    assert np.min(np.linalg.norm(path - pts[1], axis=1)) < 0.01  # the corner between the strokes is visited
    assert np.all(np.abs(path[:, 2] - 0.9) < 0.01)  # on the surface the whole way
    assert all(z[2] < -math.cos(math.radians(10)) for _, z in tool)  # tool axis kept
    length = np.linalg.norm(np.diff(path, axis=0), axis=1)
    assert length.max() < 0.008  # 0.1 m/s at 20 samples a second is 5 mm a sample
    assert length.sum() == pytest.approx(0.4 + math.hypot(0.1, 0.4), abs=0.02)


def test_pick_descends_closes_and_lifts(wheeled_xml, wheeled_build, trajectory_schema):
    grasp = [2.45, 3.0, 0.55]
    e = api.retarget(None, wheeled_xml, build=wheeled_build, task={"id": "t3", "skill": "pick"}, standoff=STANDOFF,
                     requirements=reqs("t3", [target(grasp, [0, 0, -1])]))
    arm = check_entry(e, wheeled_xml, wheeled_build, trajectory_schema)
    work = e["segments"][1]
    assert work["kind"] == "pick" and [ev["gripper"] for ev in work["events"]] == ["close"]
    p0, _ = tool_at(arm, work["samples"][0]["q"])
    assert np.allclose(p0, np.array(grasp) + [0, 0, 0.10], atol=0.01)  # starts at the pre-approach point above
    at_close = next(s for s in work["samples"] if s["t"] >= work["events"][0]["t"])
    assert np.allclose(tool_at(arm, at_close["q"])[0], grasp, atol=0.01)
    assert np.allclose(tool_at(arm, work["samples"][-1]["q"])[0], np.array(grasp) + [0, 0, 0.15], atol=0.01)


def test_legged_robot_wipes_too(spot_xml, spot_build, trajectory_schema):
    pts = [[2.55, 2.9, 0.75], [2.55, 3.1, 0.75]]
    e = api.retarget(None, spot_xml, build=spot_build, task={"id": "t2", "skill": "wipe"}, standoff=STANDOFF,
                     requirements=reqs("t2", [target(p, [0, 0, -1]) for p in pts]))
    check_entry(e, spot_xml, spot_build, trajectory_schema)


def test_out_of_reach_fails_without_raising(spot_xml, spot_build, trajectory_schema):
    e = api.retarget(None, spot_xml, build=spot_build, task={"id": "t1", "skill": "twist_out"}, standoff=STANDOFF,
                     requirements=reqs("t1", [BULB], wrist_roll_turns=3.0))
    assert e["failure"]["segment"] == "approach" and "reach" in e["failure"]["why"]
    assert e["task"] == "t1" and e["standoff"] == [2.0, 3.0, 0.0] and e["segments"] == []
    jsonschema.validate(wrap(e, spot_build), trajectory_schema)


def test_failure_in_the_work_segment_keeps_the_approach(wheeled_xml, wheeled_build, trajectory_schema):
    pts = [[2.5, 3.0, 0.9], [3.6, 3.0, 0.9]]  # the stroke runs off the end of the arm's reach
    e = api.retarget(None, wheeled_xml, build=wheeled_build, task={"id": "t2", "skill": "wipe"}, standoff=STANDOFF,
                     requirements=reqs("t2", [target(p, [0, 0, -1]) for p in pts]))
    assert e["failure"]["segment"] == "work" and "sample" in e["failure"]["why"]
    assert [s["phase"] for s in e["segments"]] == ["approach", "work"]
    jsonschema.validate(wrap(e, wheeled_build), trajectory_schema)


def test_missing_requirements_fail_cleanly(wheeled_xml, wheeled_build):
    kw = dict(build=wheeled_build, standoff=STANDOFF)
    e = api.retarget(None, wheeled_xml, task={"id": "t1", "skill": "twist_out"}, requirements=reqs("t1", [BULB]), **kw)
    assert "wrist_roll_turns" in e["failure"]["why"]
    e = api.retarget(None, wheeled_xml, task={"id": "t9", "skill": "wipe"}, requirements={"requirements": []}, **kw)
    assert "reach_targets" in e["failure"]["why"]
    e = api.retarget(None, wheeled_xml, task={"id": "t1", "skill": "navigate"}, requirements=reqs("t1", [BULB]), **kw)
    assert "navigate" in e["failure"]["why"]


def test_demo_direction_only_fills_a_missing_tool_axis(wheeled_xml, wheeled_build):
    demo = {"approach_direction": [0.0, 0.0, -2.0]}
    bare = {"point": [2.5, 3.0, 0.9], "held_axes": ["position"]}
    kw = dict(build=wheeled_build, task={"id": "t2", "skill": "wipe"}, standoff=STANDOFF)
    arm = Arm(wheeled_xml, wheeled_build)
    arm.set_base(STANDOFF["pose"])
    e = api.retarget(demo, wheeled_xml, requirements=reqs("t2", [bare]), **kw)
    assert "failure" not in e
    assert tool_at(arm, e["segments"][1]["samples"][0]["q"])[1][2] < -0.98  # the demo's direction was used
    fixed = target([2.6, 3.0, 1.2], [1, 0, 0])
    e = api.retarget(demo, wheeled_xml, requirements=reqs("t2", [fixed]), **kw)
    assert "failure" not in e
    assert tool_at(arm, e["segments"][1]["samples"][0]["q"])[1][0] > 0.98  # the requirement's axis wins


def test_same_inputs_same_trajectory(wheeled_xml, wheeled_build):
    kw = dict(build=wheeled_build, task={"id": "t1", "skill": "twist_out"}, standoff=STANDOFF,
              requirements=reqs("t1", [BULB], wrist_roll_turns=3.0))
    assert api.retarget(None, wheeled_xml, **kw) == api.retarget(None, wheeled_xml, **kw)


def test_bad_targets_fail_without_raising(wheeled_xml, wheeled_build):
    kw = dict(build=wheeled_build, task={"id": "t2", "skill": "wipe"}, standoff=STANDOFF)
    for bad in ([{"tool_axis": [0, 0, -1], "held_axes": ["position", "tool_axis"]}],
                [target([2.5, 3.0, 0.9], [0, 0, 0])],
                [target([2.5, 3.0, 0.9], [0, 0, -1]), target([2.5, 3.2, 0.9], [0, 0, 1])]):
        e = api.retarget(None, wheeled_xml, requirements=reqs("t2", bad), **kw)
        assert "failure" in e and e["failure"]["why"]


def test_tool_speed_stays_nominal(wheeled_xml, wheeled_build):
    e = api.retarget(None, wheeled_xml, build=wheeled_build, task={"id": "t1", "skill": "twist_out"}, standoff=STANDOFF,
                     requirements=reqs("t1", [BULB], wrist_roll_turns=1.0))
    arm = Arm(wheeled_xml, wheeled_build)
    arm.set_base(STANDOFF["pose"])
    for seg in e["segments"]:
        path = np.array([tool_at(arm, s["q"])[0] for s in seg["samples"]])
        assert np.linalg.norm(np.diff(path, axis=0), axis=1).max() <= 0.1 * 0.05 * 1.3


@pytest.mark.parametrize("robot, point, axis", [("wheeled", [1.7, 3.2, 0.4], [0, 0, -1]), ("wheeled", [1.8, 3.0, 0.4], [0, 0, -1]),
                                                ("spot", [2.0, 3.0, 0.7], [0, 0, -1]), ("spot", [2.1, 3.0, 1.15], [0, 0, 1])])
def test_retarget_finds_the_first_target_whenever_reachable_does(robot, point, axis, request, monkeypatch):
    """Poses `reachable` only solves on its ninth start or later. retarget tries the same starts in the same
    order (stowed, mid-range, then ik.RESTARTS draws from seed 0), so it finds them too; with the eight it
    used to try it reported "first target: out of reach" for a pose reachable had just accepted."""
    from motion import ik, trajectory
    xml, build = request.getfixturevalue(f"{robot}_xml"), request.getfixturevalue(f"{robot}_build")
    assert trajectory.CANDIDATES == 2 + ik.RESTARTS
    goal = target(point, axis)
    args = dict(build=build, task={"id": "t3", "skill": "pick"}, standoff=STANDOFF, requirements=reqs("t3", [goal]))
    assert api.reachable(xml, STANDOFF["pose"], [goal], build=build)["ok"]
    assert "failure" not in api.retarget(None, xml, **args)
    monkeypatch.setattr(trajectory, "CANDIDATES", 8)
    assert api.retarget(None, xml, **args)["failure"]["why"].startswith("first target: out of reach")
