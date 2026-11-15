import copy
import json
import math
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from nav import api
from nav import grid as G

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def _load(name):
    return json.loads((CONTRACTS / name).read_text())


@pytest.fixture()
def world():
    return _load("world.example.json")


@pytest.fixture()
def build():
    return _load("build.example.json")


@pytest.fixture()
def reqs():
    return _load("requirements.example.json")


def _rect_build(build, length, width, *, radii=True, holonomic=True):
    b = copy.deepcopy(build)
    hx, hy = length / 2, width / 2
    b["base"]["footprint"] = [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]]
    b["base"]["holonomic"] = holonomic
    if radii:
        b["base"]["inscribed_radius_m"] = min(hx, hy)
        b["base"]["circumscribed_radius_m"] = math.hypot(hx, hy)
    return b


def _standoffs(world, build, reqs):
    out = []
    for t in reqs["tasks"]:
        poses = api.propose(world, build, t, requirements=reqs)
        assert poses, t["id"]
        out.append({"task": t["id"], "pose": poses[0], "task_yaw_rad": 0.0, "reach_ok": True, "spares": poses[1:3]})
    return out


def _corners(build, pose):
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    return [(x + c * px - s * py, y + s * px + c * py) for px, py in build["base"]["footprint"]]


def _convex_overlap(a, b):
    """Separating-axis test for two convex polygons."""
    for poly in (a, b):
        for k in range(len(poly)):
            ex, ey = poly[(k + 1) % len(poly)][0] - poly[k][0], poly[(k + 1) % len(poly)][1] - poly[k][1]
            pa = [-ey * p[0] + ex * p[1] for p in a]
            pb = [-ey * p[0] + ex * p[1] for p in b]
            if max(pa) <= min(pb) or max(pb) <= min(pa):
                return False
    return True


# --- corridors ------------------------------------------------------------

def test_corridors_and_demands(world, reqs):
    before = copy.deepcopy(world)
    out = api.corridors(world, reqs["tasks"])
    assert world == before
    json.dumps(out)
    by = {c["trip"]: c for c in out["corridors"]}
    assert by["dock->t1"]["rooms"] == ["hall", "living"]
    assert by["dock->t1"]["doorways"] == ["d_living"]
    assert by["dock->t1"]["bottleneck"] == {"doorway": "d_living", "width_m": 0.76}
    assert by["dock->t2"]["bottleneck"] == {"doorway": "d_kitchen", "width_m": 0.71}
    assert by["dock->t3"]["rooms"] == ["hall", "kitchen"]
    assert by["t3->way_out"]["rooms"] == ["kitchen", "hall", "outside"]
    assert by["t3->way_out"]["doorways"] == ["d_kitchen", "d_entry"]
    assert by["t3->way_out"]["bottleneck"] == {"doorway": "d_kitchen", "width_m": 0.71}
    assert "t1->way_out" not in by
    # every corridor in the hand-written requirements example is reproduced
    for want in reqs["corridors"]:
        got = by[want["trip"]]
        assert {k: got[k] for k in want} == want
    assert out["demands"] == {"narrowest_m": 0.71, "narrowest_doorway": "d_kitchen", "lowest_header_m": 2.03,
                              "tallest_step_m": 0.0, "tightest_turn_m": 1.0, "changes_floor": False}


def test_bad_width_is_dropped_and_impassable(world, reqs):
    world["doorways"][2]["width_m"] = 0.02  # d_kitchen: a bad reading, and no mesh to re-measure
    out = api.corridors(world, reqs["tasks"])
    status = {d["id"]: d["status"] for d in out["doorways"]}
    assert status == {"d_entry": "ok", "d_living": "ok", "d_kitchen": "dropped"}
    by = {c["trip"]: c for c in out["corridors"]}
    assert by["dock->t2"]["blocked"] and by["dock->t2"]["rooms"] == []
    assert out["demands"]["narrowest_m"] == 0.76
    assert out["demands"]["narrowest_doorway"] == "d_living"
    world["doorways"][1]["width_m"] = 3.1
    assert api.corridors(world, reqs["tasks"])["demands"]["narrowest_m"] is None


def test_widest_bottleneck_and_hallway_bound(world, reqs):
    # a second, wider way into the kitchen from the living room wins over d_kitchen
    world["doorways"].append({"id": "d_side", "rooms": ["living", "kitchen"], "position": [4.0, 2.0], "along": [0, 1],
                              "width_m": 0.9, "header_m": 1.95, "step_m": 0.02, "source": "api"})
    out = api.corridors(world, reqs["tasks"])
    c = {c["trip"]: c for c in out["corridors"]}["dock->t2"]
    assert c["rooms"] == ["hall", "living", "kitchen"]
    assert c["bottleneck"] == {"doorway": "d_living", "width_m": 0.76}
    assert out["demands"]["lowest_header_m"] == 1.95
    assert out["demands"]["tallest_step_m"] == 0.02
    # a hallway narrower than its doors bounds them
    world["rooms"][0]["width_m"] = 0.6
    out = api.corridors(world, reqs["tasks"])
    assert out["demands"]["narrowest_m"] == 0.6
    assert out["demands"]["tightest_turn_m"] == 0.6


def test_changes_floor(world, reqs):
    world["floors"].append({"id": "f1", "z": 2.8})
    world["rooms"][2]["floor"] = "f1"
    assert api.corridors(world, reqs["tasks"])["demands"]["changes_floor"] is True


# --- grid -----------------------------------------------------------------

def test_grid_walls_gaps_and_obstacles(world):
    g = G.from_world(world)
    assert g.cell == 0.05
    occ = lambda x, y: bool(g.occupied_at(x, y))
    assert not occ(2.0, 0.5) and not occ(2.0, 3.0) and not occ(5.0, 1.5)
    assert occ(8.0, 1.0) and occ(2.0, -0.5)          # outside every room
    assert occ(1.0, 1.01) and not occ(2.0, 1.01)     # hall/living wall, and its doorway
    assert occ(4.01, 2.0) and not occ(4.01, 0.5)     # living/kitchen wall, kitchen doorway
    assert not occ(-0.3, 0.5)                        # apron beyond the entry
    assert occ(6.7, 1.5) and occ(1.0, 4.3)           # counter, sofa
    # the bulb's height band is above both obstacles
    high = G.from_world(world, (1.0, 2.0))
    assert not bool(high.occupied_at(6.7, 1.5))
    # doorway gaps are within one cell of the stated width
    for d in world["doorways"]:
        p, u, _ = G.door_frame(d)
        s = np.arange(-1.0, 1.0, 0.001)
        free = ~g.occupied_at(p[0] + s * u[0], p[1] + s * u[1])
        gap = free.sum() * 0.001
        assert abs(gap - d["width_m"]) <= 0.051, d["id"]


def test_rooms_join_only_through_doorways(world):
    world["doorways"][2]["source"] = "closed"  # shut the kitchen door
    g = G.from_world(world)
    reach = g.reachable(0.05, 0.6, 0.5)
    assert reach[g.index(2.0, 3.0)]
    assert not reach[g.index(5.0, 1.5)]


# --- free floor -----------------------------------------------------------

def test_free_floor(world):
    r = 0.2
    bulb = api.free_floor(world, "living_bulb", radius_m=r)
    assert bulb["edge_distance_m"] == 0.0 and bulb["side"] == [0.0, 0.0]
    # the counter is 0.6 m deep and the anchor is at its middle: the disc stops at
    # the counter's front edge, 0.3 m from the anchor, on the -x side
    counter = api.free_floor(world, "kitchen_counter", radius_m=r)
    assert 0.3 <= counter["edge_distance_m"] <= 0.36
    assert counter["side"][0] < -0.99
    assert counter["nearest"][0] <= 6.4 - r
    json.dumps(counter)
    # without the counter the disc sits against the wall instead
    world["obstacles"] = [o for o in world["obstacles"] if o["id"] != "counter"]
    assert api.free_floor(world, "kitchen_counter", radius_m=r)["edge_distance_m"] < 0.05
    # a disc too big to leave the dock reaches nothing
    assert api.free_floor(world, "kitchen_counter", radius_m=0.6)["edge_distance_m"] is None


# --- propose --------------------------------------------------------------

def test_propose(world, build, reqs):
    anchors = {a["id"]: a for a in world["anchors"]}
    reach = max(e["max_distance_m"] for e in build["reach_envelope"])
    for t in reqs["tasks"]:
        poses = api.propose(world, build, t, requirements=reqs, limit=500)
        assert len(poses) > 12
        json.dumps(poses)
        ax, ay = anchors[t["anchor"]]["point"][:2]
        room = next(r for r in world["rooms"] if r["id"] == anchors[t["anchor"]]["room"])
        xs = [p[0] for p in room["polygon"]]
        ys = [p[1] for p in room["polygon"]]
        for pose in poses:
            assert isinstance(pose, list) and len(pose) == 3
            assert 0.2 - 1e-3 <= math.hypot(pose[0] - ax, pose[1] - ay) <= reach + 1e-3
            corners = _corners(build, pose)
            for o in world["obstacles"]:
                mn, mx = o["box"]["min"], o["box"]["max"]
                box = [(mn[0], mn[1]), (mx[0], mn[1]), (mx[0], mx[1]), (mn[0], mx[1])]
                assert not _convex_overlap(corners, box), (t["id"], pose, o["id"])
            # rings near a wall must not put the base through it
            assert all(min(xs) <= cx <= max(xs) and min(ys) <= cy <= max(ys) for cx, cy in corners), (t["id"], pose)
        assert api.propose(world, build, t, requirements=reqs) == poses[:12]
        assert len({(p[0], p[1]) for p in poses[:12]}) == 12
    # the first counter pose faces the counter from its free side
    first = api.propose(world, build, reqs["tasks"][1], requirements=reqs)[0]
    assert first[0] < 6.4 and abs(first[2]) < 0.6


def test_propose_nothing_when_cut_off(world, build, reqs):
    world["doorways"][2]["width_m"] = 0.1
    assert api.propose(world, build, reqs["tasks"][1], requirements=reqs) == []


# --- plan -----------------------------------------------------------------

def _check_route(route, world, build):
    jsonschema.validate(json.loads(json.dumps(route)), _load("route.schema.json"))
    g = G.from_world(world, (0.05, build["stowed"]["height_m"]))
    samples = G.footprint_samples(build["base"]["footprint"], 0.025)
    for leg in route["legs"]:
        w = leg["waypoints"]
        for a, b in zip(w[:-1], w[1:]):
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.02))
            if n == 1 and a[:2] == b[:2]:
                continue  # a turn in place
            assert abs(a[2] - b[2]) < 1e-6 or n == 1
            for t in np.linspace(0, 1, n + 1):
                sx, sy = G.placed(samples, a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2])
                assert not g.occupied_at(sx, sy).any(), (leg["from"], leg["to"], a, b)


def test_plan_example(world, build, reqs):
    standoffs = _standoffs(world, build, reqs)
    route = api.plan(world, build, requirements=reqs, standoffs=standoffs)
    assert route["failures"] == []
    assert route["world"] == "example-flat" and route["standoffs"] == standoffs
    assert [(l["from"], l["to"]) for l in route["legs"]] == [
        ("dock", "t1"), ("t1", "t2"), ("t2", "t3"), ("t3", "way_out"), ("way_out", "dock")]
    assert [l["carrying"] for l in route["legs"]] == [False, False, False, True, False]
    dock = world["dock"]["pose"]
    assert route["legs"][0]["waypoints"][0] == dock and route["legs"][-1]["waypoints"][-1] == dock
    for a, b in zip(route["legs"][:-1], route["legs"][1:]):
        assert a["waypoints"][-1][:2] == b["waypoints"][0][:2]
    for leg, s in zip(route["legs"][:3], standoffs):
        assert leg["waypoints"][-1][:2] == s["pose"][:2]
        assert abs(math.remainder(leg["waypoints"][-1][2] - s["pose"][2], 2 * math.pi)) < 1e-3
        assert leg["length_m"] > 0
    assert route["legs"][3]["waypoints"][-1][0] < 0  # the bag ends up outside the entry
    doors = {d["doorway"]: d for d in route["door_clearances"]}
    assert set(doors) == {"d_entry", "d_living", "d_kitchen"}
    for d in world["doorways"]:
        row = doors[d["id"]]
        assert row["clear_width_m"] == d["width_m"]
        assert 0.408 - 1e-3 <= row["robot_width_m"] <= 0.606 + 1e-3
        assert row["margin_m"] == pytest.approx((row["clear_width_m"] - row["robot_width_m"]) / 2, abs=1e-3)
        assert row["margin_m"] > 0
    _check_route(route, world, build)


def test_plan_two_standoffs_and_missing_one(world, build, reqs):
    standoffs = [s for s in _load("route.example.json")["standoffs"]]  # t1, t2, t2; none for t3
    route = api.plan(world, build, requirements=reqs, standoffs=standoffs)
    jsonschema.validate(json.loads(json.dumps(route)), _load("route.schema.json"))
    assert [(l["from"], l["to"]) for l in route["legs"]] == [("dock", "t1"), ("t1", "t2"), ("t2", "t2"), ("t2", "dock")]
    assert [l.get("standoff") for l in route["legs"]] == [0, 1, 2, None]
    assert len(route["failures"]) == 1
    assert route["failures"][0]["kind"] == "no_standoff" and "t3" in route["failures"][0]["reason"]


def test_plan_base_at_the_width_ceiling_passes(world, build, reqs):
    # requirements.example.json allows a 0.61 m base through the 0.71 m kitchen doorway
    slim = _rect_build(build, 0.60, 0.60)
    standoffs = _standoffs(world, slim, reqs)
    route = api.plan(world, slim, requirements=reqs, standoffs=standoffs)
    assert route["failures"] == []
    _check_route(route, world, slim)


def test_plan_too_wide_for_a_door_is_a_recorded_failure(world, build, reqs):
    standoffs = _standoffs(world, build, reqs)
    wide = _rect_build(build, 0.9, 0.9)
    route = api.plan(world, wide, requirements=reqs, standoffs=standoffs)
    jsonschema.validate(json.loads(json.dumps(route)), _load("route.schema.json"))
    first = route["failures"][0]
    assert first["leg"] == "dock->t1" and first["kind"] == "no_route"
    assert first["doorway"] == "d_living" and "d_living" in first["reason"]
    assert abs(first["spot"][0] - 2.0) < 0.4 and abs(first["spot"][1] - 1.0) < 0.3
    assert {f["doorway"] for f in route["failures"]} >= {"d_living", "d_kitchen"}
    # nothing got through the two inner doors; the 0.86 m entry is within a cell of
    # the base on the grid, and the stated width settles it
    assert [d["doorway"] for d in route["door_clearances"]] == ["d_entry"]
    assert route["door_clearances"][0]["margin_m"] < 0
    out = next(f for f in route["failures"] if f["leg"] == "way_out->dock")
    assert out["kind"] == "footprint" and out["doorway"] == "d_entry"
    assert all(l["from"] != "dock" for l in route["legs"])


def test_plan_footprint_check_catches_what_the_radius_misses(world, build, reqs):
    standoffs = _standoffs(world, build, reqs)
    # the polygon is 0.8 m square but the radii still say 0.204 m: A* finds a
    # route and the footprint check has to reject it
    lying = _rect_build(build, 0.8, 0.8, radii=False)
    route = api.plan(world, lying, requirements=reqs, standoffs=standoffs)
    jsonschema.validate(json.loads(json.dumps(route)), _load("route.schema.json"))
    f = route["failures"][0]
    assert f["leg"] == "dock->t1" and f["kind"] == "footprint" and f["doorway"] == "d_living"
    assert route["legs"][0]["footprint_ok"] is False


def test_plan_long_base_sideways_or_not(world, build, reqs):
    # 0.85 m long, 0.5 m wide: fits the doors lengthways only, and the turn out of
    # the 1.0 m hall into d_living needs heading changes in a tight spot
    standoffs = [{"task": "t1", "pose": [2.0, 3.0, 1.5708], "task_yaw_rad": 0.0, "reach_ok": True, "spares": []}]
    tasks = dict(reqs, tasks=reqs["tasks"][:1])
    holo = api.plan(world, _rect_build(build, 0.85, 0.5), requirements=tasks, standoffs=standoffs)
    assert holo["failures"] == []
    _check_route(holo, world, _rect_build(build, 0.85, 0.5))
    assert holo["door_clearances"][0]["robot_width_m"] < 0.66  # nose first, not skewed
    car = api.plan(world, _rect_build(build, 0.85, 0.5, holonomic=False), requirements=tasks, standoffs=standoffs)
    # a base that must turn on the spot needs its 0.49 m circumscribed radius free; the hall gives 0.45 m
    assert car["failures"] and car["failures"][0]["kind"] == "footprint"
    assert "circumscribed" in car["failures"][0]["reason"]
    assert car["legs"][0]["footprint_ok"] is False


def test_plan_blocked_dock_and_closed_way_out(world, build, reqs):
    standoffs = _standoffs(world, build, reqs)
    blocked = copy.deepcopy(world)
    blocked["obstacles"].append({"id": "crate", "room": "hall", "box": {"min": [0.4, 0.2, 0.0], "max": [0.9, 0.8, 0.5]}})
    route = api.plan(blocked, build, requirements=reqs, standoffs=standoffs)
    assert route["failures"] and route["failures"][0]["kind"] == "start_blocked"
    shut = copy.deepcopy(world)
    shut["doorways"][0]["source"] = "closed"
    route = api.plan(shut, build, requirements=reqs, standoffs=standoffs)
    assert [f["kind"] for f in route["failures"]] == ["no_way_out"]
    assert [(l["from"], l["to"]) for l in route["legs"]][-1] == ("t3", "dock")


def _moving_segments(route):
    for leg in route["legs"]:
        for a, b in zip(leg["waypoints"][:-1], leg["waypoints"][1:]):
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-6:
                yield a, b


def test_plan_non_holonomic_drives_nose_first(world, build, reqs):
    car = _rect_build(build, 0.448, 0.408, holonomic=False)
    route = api.plan(world, car, requirements=reqs, standoffs=_standoffs(world, car, reqs))
    assert route["failures"] == []
    _check_route(route, world, car)
    for a, b in _moving_segments(route):
        assert abs(math.remainder(a[2] - math.atan2(b[1] - a[1], b[0] - a[0]), 2 * math.pi)) < 2e-3, (a, b)


def test_plan_sideways_through_a_door(world, build, reqs):
    # 0.5 m long, 0.8 m wide: only fits the 0.76 m doorway side on
    standoffs = [{"task": "t1", "pose": [2.0, 3.0, 0.0], "task_yaw_rad": 0.0, "reach_ok": True, "spares": []}]
    tasks = dict(reqs, tasks=reqs["tasks"][:1])
    crab = _rect_build(build, 0.5, 0.8)
    route = api.plan(world, crab, requirements=tasks, standoffs=standoffs)
    assert route["failures"] == []
    _check_route(route, world, crab)
    assert route["door_clearances"][0]["robot_width_m"] < 0.6
    through = [a for a, b in _moving_segments(route) if (a[1] - 1.0) * (b[1] - 1.0) < 0]
    assert through and all(abs(math.sin(a[2])) < 0.3 for a in through)  # heading across the travel direction
    car = api.plan(world, _rect_build(build, 0.5, 0.8, holonomic=False), requirements=tasks, standoffs=standoffs)
    assert car["failures"] and car["failures"][0]["leg"] == "dock->t1"
    assert car["failures"][0]["kind"] == "footprint"


def test_plan_navigate_waypoints_are_driven_in_order(build):
    # a navigate task carries its own poses (a coverage pattern): each becomes a stop, with no standoff and no failure
    lawn = {"schema": "world/1", "id": "lawn", "frame": "metres, Z up", "mesh": None, "floors": [{"id": "f0", "z": 0.0}],
            "rooms": [{"id": "lawn", "type": "lawn", "floor": "f0", "polygon": [[0, 0], [6, 0], [6, 5], [0, 5]], "ceiling_m": 3.0, "source": "manual"}],
            "doorways": [], "obstacles": [], "dock": {"room": "lawn", "pose": [1.0, 1.0, 0.0]}, "way_out": {"doorway": None}, "anchors": []}
    pts = [[1.0, 2.0, 0.0], [5.0, 2.0, 0.0], [5.0, 3.0, math.pi], [1.0, 3.0, math.pi]]
    task = {"id": "t1", "skill": "navigate", "anchor": None, "object": None, "carries": False, "waypoints": pts}
    small = _rect_build(build, 0.5, 0.5)
    route = api.plan(lawn, small, requirements={"tasks": [task]}, standoffs=[])
    assert route["failures"] == []
    assert [leg["to"] for leg in route["legs"]] == ["t1.1", "t1.2", "t1.3", "t1.4", "dock"]
    for leg, p in zip(route["legs"], pts):
        assert leg["waypoints"][-1] == pytest.approx(p, abs=1e-3)
    _check_route(route, lawn, small)


def test_surveyed_ground_blocks_what_stands_on_it_and_open_water(tmp_path):
    # a world on surveyed ground (ground.height): the grid takes what the survey shows standing, with nothing traced
    height = np.zeros((40, 60), np.float16)          # 6 m by 4 m at 0.1 m a pixel, row 0 at the north edge
    height[10:20, 30:40] = 1.5                       # a parked car: x 3..4, y 2..3
    height[30:34, 5:9] = 0.10                        # a kerb stone, low enough to drive over
    water = np.zeros((40, 60), bool)
    water[0:6, 50:60] = True                         # a pool in the north-east corner: x 5..6, y 3.4..4
    np.savez_compressed(tmp_path / "site.height.npz", height=height, water=water)
    yard = {"schema": "world/1", "id": "yard", "frame": "metres, Z up", "mesh": None, "floors": [{"id": "f0", "z": 0.0}],
            "ground": {"extent": [0, 0, 6, 4], "height": str(tmp_path / "site.height.npz")},
            "rooms": [{"id": "yard", "type": "yard", "floor": "f0", "polygon": [[0, 0], [6, 0], [6, 4], [0, 4]], "ceiling_m": 3.0, "source": "manual"}],
            "doorways": [], "obstacles": [], "dock": {"room": "yard", "pose": [1.0, 2.5, 0.0]}, "way_out": {"doorway": None}, "anchors": []}
    g = G.from_world(yard)
    at = lambda x, y: bool(g.occupied_at(np.array(x), np.array(y)))  # noqa: E731
    assert at(3.5, 2.5) and at(5.5, 3.7)             # the car and the pool
    assert not at(1.0, 2.5) and not at(0.7, 0.8)     # open ground, and the low kerb stone
    assert not bool(G.from_world(yard, ground=False).occupied_at(np.array(3.5), np.array(2.5)))
    assert bool(G.ground_blocked(yard, np.array(9.0), np.array(1.0)))  # outside the survey: not known, so not driven on
