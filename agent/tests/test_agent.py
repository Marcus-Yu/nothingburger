import copy
import json
import re
from pathlib import Path

import pytest

from agent import run
from agent.nodes import ledger, prepass
from agent.tools import trace

REPO = Path(__file__).resolve().parents[2]
AGENT = REPO / "agent"
CONTRACTS = REPO / "contracts"
SCRATCH = REPO / "runs" / "scratch"


def load(path):
    return json.loads(Path(path).read_text())


@pytest.fixture(scope="module")
def world():
    return load(CONTRACTS / "world.example.json")


def make_ledger(world, tasks_file="tasks.example.json", demo=True, grip=None):
    state = {"world": world, "tasks": load(AGENT / tasks_file)["tasks"]}
    if demo:
        state["demos"] = {"t1": load(CONTRACTS / "demo.example.json")}
    grip = grip if grip is not None else load(CONTRACTS / "grip.example.json")
    if grip:
        state["grips"] = {"t1": grip}
    return ledger.step(prepass.step(state))["requirements"]


@pytest.fixture(scope="module")
def requirements(world):
    return make_ledger(world)


def row(requirements, rid):
    hits = [r for r in requirements["requirements"] if r["id"] == rid]
    assert len(hits) == 1, f"{rid}: {len(hits)} rows"
    return hits[0]


# ---------------------------------------------------------------- pre-pass and ledger

def test_prepass_gives_the_building_demands(world):
    b = prepass.step({"world": world, "tasks": load(AGENT / "tasks.example.json")["tasks"]})["building"]
    assert b["demands"]["narrowest_m"] == 0.71 and b["demands"]["narrowest_doorway"] == "d_kitchen"
    assert b["demands"]["lowest_header_m"] == 2.03 and b["demands"]["tightest_turn_m"] == 1.0
    assert set(b["free_floor"]) == {"t1", "t2", "t3"} and b["radius_m"] == 0.20
    assert b["free_floor"]["t1"]["edge_distance_m"] == 0.0      # open floor under the bulb
    assert b["free_floor"]["t2"]["edge_distance_m"] > 0.2       # the counter keeps the base off its centre
    assert b["anchors"]["t1"]["height_above_floor_m"] == 2.3


def test_building_rows_by_hand(requirements):
    assert row(requirements, "r_width")["value"] == 0.61        # 0.71 - 2 x 0.05
    assert row(requirements, "r_width")["source"] == "scan:mesh"
    assert row(requirements, "r_length")["value"] == 0.9        # hall 1.0 - 2 x 0.05
    assert row(requirements, "r_header")["value"] == 1.98       # 2.03 - 0.05
    assert row(requirements, "r_step")["value"] == 0.0 and row(requirements, "r_step")["source"] == "assumed"
    assert all(row(requirements, r)["task"] is None for r in ("r_width", "r_length", "r_header", "r_step"))


def test_task_rows_by_hand(requirements):
    assert row(requirements, "r_t1_opening")["value"] == 0.07   # bulb 0.06 + 0.01
    assert row(requirements, "r_t1_payload")["value"] == 0.05
    assert row(requirements, "r_t1_roll")["value"] == 3.0
    force = row(requirements, "r_t1_force")                     # physics minimum 1.5 x 0.05 x 9.81 / (2 x 0.5) = 0.74 N
    assert force["value"] == [4.2, 9.6] and force["grip_source"] == "travel" and "uncalibrated" in force["labels"]
    press = row(requirements, "r_t2_press")
    assert (press["value"], press["tolerance"], press["source"]) == (10.0, 2.0, "assumed")
    bag = row(requirements, "r_t3_payload")
    assert bag["value"] == 1.0 and bag["source"] == "user"      # the tasks file overrides the card's 4 kg
    assert not [r for r in requirements["requirements"] if r["id"] == "r_t3_force"]  # no squeeze recorded for the bag
    assert requirements["conflicts"] == []


def test_rows_have_every_field_and_stay_per_task(requirements):
    for r in requirements["requirements"]:
        assert {"id", "task", "quantity", "value", "unit", "tolerance", "source"} <= set(r), r["id"]
    ids = [r["id"] for r in requirements["requirements"]]
    assert len(ids) == len(set(ids))
    payloads = {r["task"]: r["value"] for r in requirements["requirements"] if r["quantity"] == "payload"}
    assert payloads == {"t1": 0.05, "t2": 0.1, "t3": 1.0}       # three rows, not one maximum
    assert [c["trip"] for c in requirements["corridors"]] == ["dock->t1", "dock->t2", "dock->t3", "t3->way_out"]


def test_twist_target_is_below_the_socket_with_the_tool_up(requirements, world):
    reach = row(requirements, "r_t1_reach")
    socket = next(a for a in world["anchors"] if a["id"] == "living_bulb")
    (target,) = reach["value"]
    assert target["point"] == [2.0, 3.0, 2.27]                  # 2.30 less half the bulb's 0.06 m
    assert target["point"][2] < socket["point"][2]
    assert target["tool_axis"] == [0.0, 0.0, 1.0] and target["held_axes"] == ["position", "tool_axis"]
    assert reach["source"] == "demo:home+scan" and reach["yaw_free"] is True
    assert reach["demo_check"]["ok"] and reach["approach_direction"][2] > 0  # the hand came up at the bulb


def test_no_demo_means_assumed(world):
    r = make_ledger(world, demo=False, grip={})
    assert row(r, "r_t1_reach")["source"] == "assumed" and "demo_check" not in row(r, "r_t1_reach")
    assert row(r, "r_t1_reach")["value"][0]["point"] == [2.0, 3.0, 2.27]
    assert not [x for x in r["requirements"] if x["quantity"] == "force_band"]


def test_wipe_strokes_lie_inside_the_counter(requirements, world):
    reach = row(requirements, "r_t2_reach")
    counter = next(a for a in world["anchors"] if a["id"] == "kitchen_counter")
    xs, ys = [p[0] for p in counter["extent"]], [p[1] for p in counter["extent"]]
    targets = reach["value"]
    assert len(targets) == 26 and reach["strokes"] == 13        # 1.9 m of inset length at 0.15 m: 13 lanes
    for t in targets:
        x, y, z = t["point"]
        assert min(xs) + 0.05 - 1e-9 <= x <= max(xs) - 0.05 + 1e-9
        assert min(ys) + 0.05 - 1e-9 <= y <= max(ys) - 0.05 + 1e-9
        assert z == 0.92 and t["tool_axis"] == [0.0, 0.0, -1.0]
    lanes = [targets[2 * k]["point"][1] for k in range(13)]
    assert all(targets[2 * k]["point"][1] == targets[2 * k + 1]["point"][1] for k in range(13))  # a stroke stays in its lane
    assert all(abs((b - a) - 0.15) < 1e-6 for a, b in zip(lanes, lanes[1:]))
    assert all({targets[2 * k]["point"][0], targets[2 * k + 1]["point"][0]} == {6.45, 6.95} for k in range(13))
    assert targets[0]["point"][0] == 6.45                       # starts at the free-floor side
    assert targets[1]["point"] [0] == targets[2]["point"][0]    # serpentine


def test_every_reach_target_has_its_own_free_floor(requirements):
    """The counter is 0.6 m deep: the far stroke ends are farther from any floor the base can stand on than the
    counter's centre (the task's free_floor row), the near ends closer. Open floor under the bulb and at the bin."""
    centre = row(requirements, "r_t2_floor")["value"]["edge_distance_m"]
    targets = row(requirements, "r_t2_reach")["value"]
    assert all(isinstance(t["edge_distance_m"], float) and len(t["side"]) == 2 for t in targets)
    near = [t["edge_distance_m"] for t in targets if t["point"][0] == 6.45]
    far = [t["edge_distance_m"] for t in targets if t["point"][0] == 6.95]
    assert len(near) == len(far) == 13 and max(near) < centre < max(far)
    assert max(far) == pytest.approx(0.55, abs=0.03)             # 6.95 back to x = 6.4, less nothing: the disc's edge
    middle = next(t for t in targets if t["point"] == [6.95, 1.5, 0.92])
    assert middle["edge_distance_m"] == max(far) and middle["side"][0] < -0.99   # the floor is on the room side
    for rid in ("r_t1_reach", "r_t3_reach"):
        (t,) = row(requirements, rid)["value"]
        assert t["edge_distance_m"] == 0.0 and t["side"] == [0.0, 0.0]


def test_design_and_pathing_agree_on_the_deep_counter(example_run):
    """The reach check now holds for every stroke end, so the robot designed is one whose arm gets to the far
    side of the counter, and pathing covers all 13 strokes with arm paths that succeed."""
    _, out = example_run
    design, route, traj = load(out / "design.json"), load(out / "route.json"), load(out / "trajectory.json")
    reach = next(c for c in design["checks"] if c["check"] == "reach" and c["task"] == "t2")
    assert reach["status"] == "pass" and len(reach["targets"]) == 26
    tight = reach["targets"][reach["target"]]
    assert tight["needed_m"] == max(t["needed_m"] for t in reach["targets"]) > 0.7 and tight["reach_m"] >= tight["needed_m"]
    assert design["parts"]["arm"] != "xarm7"                     # 0.70 m of reach at counter height is not enough
    mine = [s for s in route["standoffs"] if s["task"] == "t2"]
    assert sorted(i for s in mine for i in s["covers_targets"]) == list(range(26))
    assert all(s["reach_ok"] and s["tip_ratio"] >= 1.5 for s in mine)
    paths = [e for e in traj["tasks"] if e["task"] == "t2"]
    assert len(paths) == len(mine) and all("failure" not in e for e in paths)
    assert not route["failures"] and not traj["failures"]


def test_pick_target_points_into_the_surface(requirements):
    (target,) = row(requirements, "r_t3_reach")["value"]
    assert target["point"] == [4.5, 2.6, 0.55] and target["tool_axis"] == [0.0, 0.0, -1.0]
    assert row(requirements, "r_t3_reach")["source"] == "assumed"


def test_empty_force_band_is_a_conflict_and_only_a_glove_asks(world):
    grip = load(CONTRACTS / "grip.example.json")
    grip["force_n"] = {"min": 0.1, "max": 0.3, "peak": 0.5}     # under the 0.74 N needed to pinch the bulb
    for source, ask in (("glove", True), ("travel", False)):
        r = make_ledger(world, grip=dict(grip, source=source))
        (c,) = r["conflicts"]
        assert c["kind"] == "empty_force_band" and c["task"] == "t1" and c["ask_user"] is ask
        assert c["low_n"] == 0.74 and c["high_n"] == 0.5
        assert not [x for x in r["requirements"] if x["quantity"] == "force_band"]


def test_hook_hold_has_no_physics_minimum():
    grip = {"source": "glove", "force_n": {"min": 0.0, "max": 6.0, "peak": 8.0}}
    made, conflict = ledger._force_band("t3", ledger.object_card("trash_bag"), 4.0, grip)
    assert conflict is None and made["value"] == [0.0, 8.0]
    made, conflict = ledger._force_band("t3", dict(ledger.object_card("trash_bag"), hold="pinch"), 4.0, grip)
    assert made is None and conflict["low_n"] == 58.86          # 1.5 x 4 x 9.81 / (2 x 0.5)


def test_fixture_frame_follows_the_demo_frame_rule():
    R, origin, yaw_free = ledger.fixture_frame({"point": [1, 2, 3], "normal": [0, 0, -1]})
    assert yaw_free and list(R[:, 2]) == [0, 0, -1] and list(origin) == [1, 2, 3]
    R, _, yaw_free = ledger.fixture_frame({"point": [0, 0, 1], "normal": [1, 0, 0]})  # a wall fixture
    assert not yaw_free and abs(R[2, 0]) < 1e-9 and list(R[:, 2]) == [1, 0, 0]       # x horizontal, z out of the wall
    assert abs(abs(float(R[:, 1] @ [0, 0, 1])) - 1) < 1e-9


# ---------------------------------------------------------------- the rule on imports

def test_only_tools_import_the_modules():
    pattern = re.compile(r"^\s*(from|import)\s+(composer|nav|motion)\b", re.M)
    for path in AGENT.rglob("*.py"):
        if "tools" in path.relative_to(AGENT).parts or "tests" in path.relative_to(AGENT).parts:
            continue
        assert not pattern.search(path.read_text()), f"{path} imports a module directly"


# ---------------------------------------------------------------- full runs

@pytest.fixture(scope="module")
def example_run():
    out = SCRATCH / "test_example"
    code = run.main(["--world", str(CONTRACTS / "world.example.json"), "--tasks", str(AGENT / "tasks.example.json"),
                     "--demo", str(CONTRACTS / "demo.example.json"), "--grip", str(CONTRACTS / "grip.example.json"),
                     "--demo-task", "t1", "--out", str(out)])
    return code, out


def test_full_run_exits_zero_and_every_file_validates(example_run):
    code, out = example_run
    assert code == 0
    for name in run.OUTPUTS:
        assert (out / name).exists(), name
    checked = run.validate_run(out)
    assert {n for n, _ in checked} == {"world.json", "demo.json", "grip.json", "requirements.json", "design.json",
                                       "build.json", "route.json", "trajectory.json", "program.json"}
    assert all(err is None for _, err in checked), checked


def test_full_run_contents(example_run):
    _, out = example_run
    design, route, traj = load(out / "design.json"), load(out / "route.json"), load(out / "trajectory.json")
    assert design["parts"] is not None and design["price_usd"] > 0
    decisions = [json.loads(line) for line in (out / "decisions.jsonl").read_text().splitlines()]
    slots = [d for d in decisions if d["slot"] != "loop"]  # a redesign adds a "loop" entry per robot fix
    assert [d["slot"] for d in slots] == list(design["parts"])
    assert all(d["chosen"] == design["parts"][d["slot"]] and d["price_usd"] == design["price_usd"] for d in slots)
    assert len(decisions) - len(slots) <= run.MAX_ROBOT_FIXES
    # the bulb and the bag each get a standoff that passes reach, and an arm path
    for tid in ("t1", "t3"):
        (s,) = [s for s in route["standoffs"] if s["task"] == tid]
        assert s["reach_ok"] and s["tip_ratio"] >= 1.5 and len(s["spares"]) <= 2
        (e,) = [e for e in traj["tasks"] if e["task"] == tid]
        assert "failure" not in e and [g["phase"] for g in e["segments"]] == ["approach", "work", "retreat"]
        assert e["standoff"] == s["pose"]
    assert traj["joints"] == load(out / "build.json")["arm_joints"]
    # every task either has a standoff or a recorded failure; nothing is dropped silently
    for tid in ("t1", "t2", "t3"):
        assert [s for s in route["standoffs"] if s["task"] == tid] or [f for f in route["failures"] if f.get("task") == tid]
    # wipe standoffs say which targets they cover, and their arm paths were built on those alone
    for s in (s for s in route["standoffs"] if s["task"] == "t2"):
        assert s["covers_targets"] and s["covers"].startswith("strokes ")
    names = {c["name"] for c in load(out / "trace.json")["calls"]}
    assert {"nav.corridors", "nav.free_floor", "composer.design", "composer.compose", "nav.propose", "motion.reachable",
            "nav.plan", "motion.retarget"} <= names
    assert all({"name", "seconds", "summary"} <= set(c) for c in load(out / "trace.json")["calls"])


def test_four_kg_bag_ends_infeasible_and_names_its_binding_checks(capsys):
    out = SCRATCH / "test_heavy_bag"
    code = run.main(["--world", str(CONTRACTS / "world.example.json"), "--tasks", str(AGENT / "tasks.heavy_bag.json"),
                     "--demo", str(CONTRACTS / "demo.example.json"), "--grip", str(AGENT / "grip.glove.example.json"),
                     "--demo-task", "t1", "--out", str(out)])
    printed = capsys.readouterr().out
    assert code == 0 and "INFEASIBLE" in printed and "binding: payload / t3" in printed
    design = load(out / "design.json")
    assert design["parts"] is None
    binding = design["infeasible"]["binding_checks"]
    assert binding and all(c["status"] == "fail" for c in binding)
    assert {"r_t3_payload"} <= {r for c in binding for r in c["requirements"]}
    assert not (out / "route.json").exists() and not (out / "trajectory.json").exists() and not (out / "robot.xml").exists()
    (decision,) = [json.loads(line) for line in (out / "decisions.jsonl").read_text().splitlines()]
    assert decision["infeasible"] and decision["binding_checks"] == binding
    assert all(err is None for _, err in run.validate_run(out))


def test_only_targets_cuts_one_tasks_row(requirements):
    from agent.nodes import pathing
    cut = pathing._only_targets(requirements, "t2", [4, 5])
    assert [t["point"] for t in row(cut, "r_t2_reach")["value"]] == [t["point"] for t in row(requirements, "r_t2_reach")["value"][4:6]]
    assert len(row(requirements, "r_t2_reach")["value"]) == 26 and row(cut, "r_t1_reach") is row(requirements, "r_t1_reach")


def test_a_shallow_counter_is_wiped_from_several_standoffs(world):
    """Cut to 0.35 m deep, the counter is within the cheapest arm's reach (the xarm7), but no single pose
    reaches all 13 strokes, so the strokes are covered by several standoffs in order."""
    shallow = copy.deepcopy(world)
    counter = next(a for a in shallow["anchors"] if a["id"] == "kitchen_counter")
    counter["extent"], counter["point"] = [[6.4, 0.5], [6.75, 0.5], [6.75, 2.5], [6.4, 2.5]], [6.575, 1.5, 0.92]
    trace.reset()
    state = run.pipeline({"world": shallow, "tasks_file": str(AGENT / "tasks.example.json")})
    mine = [s for s in state["route"]["standoffs"] if s["task"] == "t2"]
    assert len(mine) > 1 and all(s["reach_ok"] for s in mine)
    covered = [i for s in mine for i in s["covers_targets"]]
    assert covered == list(range(26))                           # every stroke once, in order along the surface
    assert not [f for f in state["route"]["failures"] if f.get("task") == "t2"]
    paths = [e for e in state["trajectory"]["tasks"] if e["task"] == "t2"]
    assert len(paths) == len(mine) and all("failure" not in e for e in paths)
    assert [e["covers_targets"] for e in paths] == [s["covers_targets"] for s in mine]
    legs = [(leg["from"], leg["to"]) for leg in state["route"]["legs"]]
    assert legs.count(("t2", "t2")) == len(mine) - 1 and legs[-2:] == [("t3", "way_out"), ("way_out", "dock")]


def test_a_failed_arm_path_is_retried_from_a_spare(monkeypatch):
    from agent.nodes import pathing
    task = {"id": "t3", "skill": "pick", "anchor": "kitchen_bin", "carries": False}
    target = {"point": [0, 0, 0.5], "tool_axis": [0, 0, -1], "held_axes": ["position", "tool_axis"]}
    requirements = {"tasks": [task], "requirements": [{"id": "r", "task": "t3", "quantity": "reach_targets", "value": [target]}]}
    picked = {"task": "t3", "pose": [1.0, 0.0, 0.0], "task_yaw_rad": 0.0, "reach_ok": True, "tip_ratio": 9.0,
              "spares": [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]]}
    planned = []

    def retarget(demo, robot, *, build, task, standoff, requirements, obstacles=None):
        entry = {"task": task["id"], "standoff": list(standoff["pose"]), "segments": []}
        if standoff["pose"][0] < 3.0:  # only the second spare works
            entry["failure"] = {"segment": "approach", "why": "first target: out of reach"}
        return entry

    def plan(world, build, *, requirements, standoffs):
        planned.append([s["pose"] for s in standoffs])
        return {"schema": "route/1", "world": None, "standoffs": [dict(s) for s in standoffs], "legs": [],
                "door_clearances": [], "failures": []}

    monkeypatch.setattr(pathing, "pick_standoffs", lambda state, task: ([picked], []))
    monkeypatch.setattr(pathing.motion, "retarget", retarget)
    monkeypatch.setattr(pathing.motion, "reachable", lambda *a, **k: {"ok": True, "tip_ratio": 5.0, "q": {}, "missed": [], "why": "ok"})
    monkeypatch.setattr(pathing.nav, "plan", plan)
    out = pathing.step({"world": {}, "requirements": requirements, "build": {"arm_joints": ["j"]}, "robot_xml": "<mujoco/>"})
    (s,) = out["route"]["standoffs"]
    assert s["pose"] == [3.0, 0.0, 0.0] and s["tip_ratio"] == 5.0 and s["spares"] == []
    assert [r["pose"] for r in s["rejected"]] == [[2.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    assert planned == [[[1.0, 0.0, 0.0]], [[3.0, 0.0, 0.0]]]      # planned again after the swap
    assert out["trajectory"]["failures"] == [] and out["trajectory"]["tasks"][0]["standoff"] == [3.0, 0.0, 0.0]


def test_a_failed_arm_path_goes_on_down_the_proposals_after_the_spares(monkeypatch):
    """Every pose at the nearest ring passes reach but the arm cannot leave its stowed pose there (the ur5e at
    the bin): after the spares, further proposals are tried until one gives an arm path."""
    from agent.nodes import pathing
    task = {"id": "t3", "skill": "pick", "anchor": "kitchen_bin", "carries": False}
    target = {"point": [0, 0, 0.5], "tool_axis": [0, 0, -1], "held_axes": ["position", "tool_axis"]}
    requirements = {"tasks": [task], "requirements": [{"id": "r", "task": "t3", "quantity": "reach_targets", "value": [target]}]}
    picked = {"task": "t3", "pose": [1.0, 0.0, 0.0], "task_yaw_rad": 0.0, "reach_ok": True, "tip_ratio": 9.0, "spares": [[2.0, 0.0, 0.0]]}

    def retarget(demo, robot, *, build, task, standoff, requirements, obstacles=None):
        entry = {"task": task["id"], "standoff": list(standoff["pose"]), "segments": []}
        if standoff["pose"][0] < 4.0:
            entry["failure"] = {"segment": "approach", "why": "the joint-space move puts the arm into the base"}
        return entry

    monkeypatch.setattr(pathing, "pick_standoffs", lambda state, task: ([picked], []))
    monkeypatch.setattr(pathing.motion, "retarget", retarget)
    monkeypatch.setattr(pathing.motion, "reachable", lambda *a, **k: {"ok": True, "tip_ratio": 5.0, "q": {}, "missed": [], "why": "ok"})
    monkeypatch.setattr(pathing.nav, "propose", lambda *a, **k: [[x, 0.0, 0.0] for x in (1.0, 2.0, 3.0, 4.0, 5.0)])
    monkeypatch.setattr(pathing.nav, "plan", lambda world, build, *, requirements, standoffs: {
        "schema": "route/1", "world": None, "standoffs": [dict(s) for s in standoffs], "legs": [], "door_clearances": [], "failures": []})
    out = pathing.step({"world": {}, "requirements": requirements, "build": {"arm_joints": ["j"]}, "robot_xml": "<mujoco/>"})
    (s,) = out["route"]["standoffs"]
    assert s["pose"] == [4.0, 0.0, 0.0] and s["reach_ok"] and s["tip_ratio"] == 5.0
    assert [r["pose"] for r in s["rejected"]] == [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    assert out["trajectory"]["failures"] == [] and out["trajectory"]["tasks"][0]["standoff"] == [4.0, 0.0, 0.0]


def test_a_demo_belongs_to_the_first_task_its_motion_shows():
    from agent.run import _demo_task
    tasks = [{"id": "t1", "skill": "pick"}, {"id": "t2", "skill": "wipe"}, {"id": "t3", "skill": "wipe"}]
    assert _demo_task({"tasks": tasks, "demo": {"motion": {"kind": "wipe"}}}) == "t2"
    assert _demo_task({"tasks": tasks, "demo": {"motion": {"kind": "twist"}}}) == "t1"
    assert _demo_task({"tasks": tasks}) == "t1"
