import json

import numpy as np
import pytest

from motion import api
from motion.ik import Arm

from .conftest import target

POSE = [2.0, 3.0, 0.7]  # parked directly under the fixture, at an arbitrary heading
BULB = target([2.0, 3.0, 2.24], [0, 0, 1])


def test_ceiling_above_the_base_is_reachable_with_a_lift(wheeled_xml, wheeled_build):
    r = api.reachable(wheeled_xml, POSE, [BULB], build=wheeled_build)
    assert r["ok"], r["why"]
    assert r["missed"] == [] and r["tip_ratio"] >= 1.5
    assert list(r["q"]) == wheeled_build["arm_joints"]
    json.dumps(r)  # plain data, no infinity
    # the answer really puts the tool there, inside the joint limits, clear of the robot
    arm = Arm(wheeled_xml, wheeled_build)
    arm.set_base(POSE)
    q = np.array(list(r["q"].values()))
    arm.set(q)
    pe, ae = arm.errors(BULB["point"], np.array(BULB["tool_axis"], dtype=float))
    assert pe < 0.01 and ae < 10.0
    assert arm.within(q) and not arm.collides()
    assert 0.0 <= r["q"]["lift"] <= 0.5


def test_ceiling_is_out_of_range_without_a_lift(spot_xml, spot_build):
    r = api.reachable(spot_xml, POSE, [BULB], build=spot_build)
    assert not r["ok"] and r["missed"] == [0] and r["q"] == {}
    assert "reach" in r["why"]
    # the same robot does reach a point it can get to, with its legs held at the stance
    low = api.reachable(spot_xml, POSE, [target([2.3, 3.2, 1.2], [0, 0, 1])], build=spot_build)
    assert low["ok"], low["why"]


def test_ceiling_too_high_for_the_lift_robot(wheeled_xml, wheeled_build):
    r = api.reachable(wheeled_xml, POSE, [target([2.0, 3.0, 3.2], [0, 0, 1])], build=wheeled_build)
    assert not r["ok"] and r["missed"] == [0]


def test_far_point_is_missed_by_index(wheeled_xml, wheeled_build):
    near = target([2.4, 3.2, 1.1], [0, 0, -1])
    far = target([6.0, 3.0, 1.0], [1, 0, 0])
    r = api.reachable(wheeled_xml, POSE, [near, far, near], build=wheeled_build)
    assert not r["ok"] and r["missed"] == [1]
    assert r["q"] and "target 1" in r["why"]


def test_tip_ratio_drops_as_payload_rises(wheeled_xml, wheeled_build):
    out = target([2.0 + 0.75, 3.0, 1.2], [1, 0, 0])  # arm stretched out sideways
    pose = [2.0, 3.0, 0.0]
    tips = [api.reachable(wheeled_xml, pose, [out], build=wheeled_build, payload_kg=kg)["tip_ratio"] for kg in (0.0, 3.0, 30.0)]
    assert tips[0] > tips[1] > tips[2]
    heavy = api.reachable(wheeled_xml, pose, [out], build=wheeled_build, payload_kg=30.0)
    assert heavy["missed"] == [] and not heavy["ok"] and "tip" in heavy["why"]
    # a downward force on the tool (pushing up on a ceiling out there) tips the robot the same way;
    # an upward one (the reaction to pressing down on a counter) does not
    down = api.reachable(wheeled_xml, pose, [out], build=wheeled_build, tool_force_z_n=-50.0)["tip_ratio"]
    up = api.reachable(wheeled_xml, pose, [out], build=wheeled_build, tool_force_z_n=10.0)["tip_ratio"]
    assert down < tips[0] <= up


def test_same_inputs_same_answer(wheeled_xml, wheeled_build):
    ts = [target([2.5, 3.3, 0.9], [0, 0, -1]), BULB]
    a = api.reachable(wheeled_xml, POSE, ts, build=wheeled_build, payload_kg=1.0)
    b = api.reachable(wheeled_xml, POSE, ts, build=wheeled_build, payload_kg=1.0)
    assert a == b


def test_base_pose_is_respected(wheeled_xml, wheeled_build):
    """The same target in the base frame, at two base poses, gives the same joint answer."""
    local = np.array([0.45, 0.2, 1.3])
    qs = []
    for x, y, th in ([0, 0, 0], [3.0, -1.0, 2.1]):
        c, s = np.cos(th), np.sin(th)
        p = [x + c * local[0] - s * local[1], y + s * local[0] + c * local[1], local[2]]
        r = api.reachable(wheeled_xml, [x, y, th], [target(p, [c, s, 0])], build=wheeled_build)
        assert r["ok"], r["why"]
        qs.append(list(r["q"].values()))
    assert np.allclose(qs[0], qs[1], atol=1e-3)


def test_position_only_target(wheeled_xml, wheeled_build):
    t = {"point": [2.5, 3.0, 1.0], "tool_axis": [0, 0, 1], "held_axes": ["position"]}
    assert api.reachable(wheeled_xml, [2.0, 3.0, 0.0], [t], build=wheeled_build)["ok"]


def test_solution_inside_the_base_is_rejected(wheeled_xml, wheeled_build):
    inside = target([2.0, 3.0, 0.2], [0, 0, -1])  # inside the base box
    r = api.reachable(wheeled_xml, [2.0, 3.0, 0.0], [inside], build=wheeled_build)
    assert not r["ok"] and r["missed"] == [0]


@pytest.mark.parametrize("robot", ["wheeled", "spot"])
def test_solver_finds_poses_known_to_exist(robot, request):
    """Targets taken from random collision-free arm poses: the solver should find nearly all."""
    xml, build = request.getfixturevalue(robot + "_xml"), request.getfixturevalue(robot + "_build")
    arm = Arm(xml, build)
    rng = np.random.default_rng(3)
    made = solved = 0
    while made < 40:
        arm.set(rng.uniform(arm.lo, arm.hi))
        if arm.collides():
            continue
        made += 1
        t = target(arm.tool_pos(), arm.tool_axis())
        solved += api.reachable(xml, [0, 0, 0], [t], build=build)["missed"] == []
    assert solved >= 38, f"{solved}/40"


def test_solution_through_the_floor_is_rejected(wheeled_xml, wheeled_build):
    """Neither fixture's arm gets down to z = 0, so the floor plane is raised to 1 m for this test.
    A tool tip 3 cm under it is within reach, but the gripper would be in the floor."""
    floor = '<geom name="floor" '
    assert floor in wheeled_xml
    xml = wheeled_xml.replace(floor, floor + 'pos="0 0 1.0" ')
    under = target([0.5, 0.2, 0.97], [0, 0, -1])
    assert api.reachable(wheeled_xml, [0, 0, 0], [under], build=wheeled_build)["ok"]
    r = api.reachable(xml, [0, 0, 0], [under], build=wheeled_build)
    assert not r["ok"] and r["missed"] == [0]
    assert "floor" in r["why"] and "out of reach" not in r["why"], r["why"]
    above = target([0.5, 0.2, 1.05], [0, 0, -1])
    assert api.reachable(xml, [0, 0, 0], [above], build=wheeled_build)["ok"]
