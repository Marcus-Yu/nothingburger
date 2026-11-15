"""The Matterport loader on a hand-written Model API record and a hand-written mesh: no network."""
import json
import sys
from pathlib import Path

import pytest

from nav import api as nav
from world import matterport

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "contracts"))
import validate  # noqa: E402

P = {"a": (0, 0), "b": (4, 0), "c": (4, 1.2), "d": (0, 1.2), "e": (0, 5), "f": (2, 5), "g": (4, 5), "h": (2, 4),
     "i": (8, 0), "j": (8, 5)}


def _edge(name, kind="wall", openings=()):
    return {"id": name, "type": kind, "thickness": 0.14, "vertices": [{"id": name[0]}, {"id": name[1]}],
            "openings": list(openings)}


def _door(width, centre, kind="doorway", low=0.0):
    return {"id": f"o{width}{centre}", "type": kind, "label": "door-pivot", "width": width, "height": 2.03,
            "lowerElevation": low, "relativeCenter": centre}


def _room(label, edges, height=None):
    return {"id": label or "none", "floor": {"id": "F"}, "classifications": [{"label": label}] if label else [],
            "dimensions": {}, "ceiling": {"minHeight": height} if height else {},
            "boundary": {"edges": [{"id": e} for e in edges]}, "holes": []}


@pytest.fixture()
def model():
    """A hallway with the front door, a kitchen off it with a wall stub, and a living room open to the hallway."""
    edges = [_edge("ab"), _edge("bc", "invisible"), _edge("cd", openings=[_door(0.8, 0.75)]),
             _edge("da", openings=[_door(0.9, 0.5, low=0.02)]), _edge("de"), _edge("ef"), _edge("fg"),
             _edge("gc", openings=[_door(1.2, 0.5, kind="window")]), _edge("fh"), _edge("bi"), _edge("ij"), _edge("jg")]
    return {"id": "TESTMODEL01", "name": "Test house", "address": {"address": "1 Test St"},
            "floors": [{"id": "F", "label": "Floor 1", "sequence": 0, "edges": edges,
                        "vertices": [{"id": k, "position": {"x": x, "y": y}} for k, (x, y) in P.items()]}],
            "rooms": [_room("Hallway", ["ab", "bc", "cd", "da"], 2.5), _room("Kitchen", ["cd", "de", "ef", "fg", "gc", "fh"], 2.6),
                      _room("Living Room", ["bc", "bi", "ij", "jg", "gc"]), _room("Void", ["ab"]), _room(None, [])],
            "locations": [{"id": "p1", "position": {"x": 1, "y": 0.6, "z": 0.02}, "floor": {"id": "F"}}]}


def _quad(lines, corners):
    n = sum(1 for l in lines if l.startswith("v ")) + 1
    lines += [f"v {x} {y} {z}" for x, y, z in corners] + [f"f {n} {n + 1} {n + 2} {n + 3}"]


def _door_between(world, a, b):
    return [d for d in world["doorways"] if set(d["rooms"]) == {a, b}]


def test_floor_plan(model):
    world = matterport.build(model, name="test_house")
    validate.validate("world", world)
    assert [r["id"] for r in world["rooms"]] == ["hallway", "kitchen", "living_room"]
    assert world["floors"] == [{"id": "f1", "z": 0.0}] and world["tour"]["to_model"][1] == [0.0, 0.0, 1.0, 0.02]
    assert world["tour"]["matterport"] == "TESTMODEL01"

    (inner,) = _door_between(world, "hallway", "kitchen")       # 0.75 of the way from c (4, 1.2) to d (0, 1.2)
    assert inner["position"] == [1.0, 1.2] and abs(inner["along"][0]) == 1 and inner["width_m"] == 0.8
    (front,) = _door_between(world, "outside", "hallway")
    assert front["rooms"][0] == "outside" and front["header_m"] == 2.05 and front["step_m"] == 0.02
    (open_side,) = _door_between(world, "hallway", "living_room")  # the invisible wall: all of it is passage
    assert open_side["width_m"] == 1.2 and open_side["position"] == [4.0, 0.6]
    assert not _door_between(world, "kitchen", "living_room")    # a window is not a way through

    kitchen = next(r for r in world["rooms"] if r["id"] == "kitchen")
    assert len(kitchen["polygon"]) == 5                          # the stub's far end is not a corner
    assert [o["id"] for o in world["obstacles"]] == ["wall_stub_1"]
    living = next(r for r in world["rooms"] if r["id"] == "living_room")
    assert living["ceiling_m"] == matterport.CEILING_M and "assumed" in living["note"]
    assert world["anchors"] == [] and "no mesh" in world["source"]


def test_nav_can_use_it(model):
    world = matterport.build(model, name="test_house")
    assert world["way_out"] == {"doorway": _door_between(world, "outside", "hallway")[0]["id"]}
    assert world["dock"]["room"] == "hallway"
    world["anchors"] = [{"id": f"{room}_spot", "room": room, "kind": "surface", "point": [x, y, 0.75], "normal": [0, 0, 1],
                         "source": "manual"} for room, x, y in (("kitchen", 1.0, 3.0), ("living_room", 6.0, 2.5))]
    tasks = [{"id": f"t{n}", "skill": "wipe", "anchor": a["id"], "object": "cloth", "carries": False}
             for n, a in enumerate(world["anchors"], 1)]
    found = nav.corridors(world, tasks)
    assert all(d["status"] == "ok" for d in found["doorways"])
    assert [c["rooms"][-1] for c in found["corridors"]] == ["kitchen", "living_room"]
    assert not any(c.get("blocked") for c in found["corridors"])
    # the doors cut gaps in the walls: a 0.2 m disc gets from the dock to both spots on the floor grid
    for a in world["anchors"]:
        assert nav.free_floor(world, a["id"], radius_m=0.2)["edge_distance_m"] == pytest.approx(0.0, abs=0.06)


def test_a_door_into_unscanned_space_is_not_a_way_out(model):
    model["rooms"][3] = _room("Void", ["da"])       # the record puts a void, not the street, behind the front door
    world = matterport.build(model, name="test_house")
    validate.validate("world", world)
    (front,) = [d for d in world["doorways"] if d["rooms"][0] == "outside"]
    assert front["source"] == "closed"
    assert world["way_out"]["doorway"] is None and "no way out" in world["way_out"]["note"]
    assert world["dock"]["room"] == "hallway"        # two doors, more than any other room
    x, y, _ = world["dock"]["pose"]
    assert (x, y) == pytest.approx((2.0, 0.6), abs=1.5) and 0.45 <= y <= 0.75    # mid-width of the 1.2 m hallway


def test_the_dock_keeps_clear_of_furniture(model, tmp_path):
    """A cabinet fills the hallway just inside the front door: the dock moves past it."""
    lines: list = []
    for z in (0.5, 1.0):
        _quad(lines, [(0.3, 0.1, z), (1.6, 0.1, z), (1.6, 1.1, z), (0.3, 1.1, z)])
    for (ax, ay), (bx, by) in (((0.3, 0.1), (1.6, 0.1)), ((1.6, 0.1), (1.6, 1.1)), ((1.6, 1.1), (0.3, 1.1)), ((0.3, 1.1), (0.3, 0.1))):
        _quad(lines, [(ax, ay, 0.02), (bx, by, 0.02), (bx, by, 1.0), (ax, ay, 1.0)])
    obj = tmp_path / "hall.obj"
    obj.write_text("\n".join(lines) + "\n")
    world = matterport.build(model, name="test_house", mesh=obj)
    x, y, _ = world["dock"]["pose"]
    assert world["dock"]["room"] == "hallway" and x >= 1.6 + 0.4
    world["anchors"] = [{"id": "spot", "room": "living_room", "kind": "surface", "point": [6.0, 2.5, 0.75],
                         "normal": [0, 0, 1], "source": "manual"}]
    assert nav.free_floor(world, "spot", radius_m=0.25)["edge_distance_m"] is not None


def test_only_the_biggest_floor_is_kept(model):
    floor = model["floors"][0]
    model["floors"].append({"id": "G", "label": "Basement", "sequence": -1, "edges": [
        {"id": k, "type": "wall", "thickness": 0.1, "vertices": [{"id": k[:2]}, {"id": k[2:]}], "openings": []}
        for k in ("b1b2", "b2b3", "b3b4", "b4b1")],
        "vertices": [{"id": f"b{n}", "position": {"x": x, "y": y}} for n, (x, y) in enumerate(((0, 0), (3, 0), (3, 3), (0, 3)), 1)]})
    cellar = _room("Garage", ["b1b2", "b2b3", "b3b4", "b4b1"])
    cellar["floor"] = {"id": "G"}
    model["rooms"].append(cellar)
    model["locations"].append({"id": "p2", "position": {"x": 1, "y": 1, "z": -2.9}, "floor": {"id": "G"}})
    world = matterport.build(model, name="test_house")
    assert [f["id"] for f in world["floors"]] == ["f2"] and world["floors"][0]["z"] == 0.0
    assert "garage" not in [r["id"] for r in world["rooms"]]
    assert "Basement (1 rooms)" in world["source"] and floor["label"] in world["source"]


def test_wide_openings_are_cut(model):
    model["floors"][0]["edges"][7]["openings"] = [_door(3.2, 0.5, kind="opening")]   # kitchen to living room
    world = matterport.build(model, name="test_house")
    parts = _door_between(world, "kitchen", "living_room")
    assert len(parts) == 2 and all(d["width_m"] == 1.6 for d in parts)
    assert all(d["status"] == "ok" for d in nav.corridors(world, [])["doorways"])


def test_no_plan(model):
    model["rooms"] = [r for r in model["rooms"] if not r["boundary"]["edges"]]
    with pytest.raises(matterport.NoPlan):
        matterport.build(model)


def test_furniture_from_mesh(model, tmp_path):
    """A 1.5 by 1.0 m table 0.75 m high in the living room, with a lamp hanging over its middle."""
    x0, x1, y0, y1, z = 5.0, 6.5, 2.0, 3.0, 0.77
    lines: list = []
    _quad(lines, [(0, 0, 0.02), (8, 0, 0.02), (8, 5, 0.02), (0, 5, 0.02)])                # the floor
    _quad(lines, [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)])                    # the top
    for (ax, ay), (bx, by) in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        _quad(lines, [(ax, ay, 0.02), (bx, by, 0.02), (bx, by, z), (ax, ay, z)])          # its sides
    _quad(lines, [(5.6, 2.4, 1.85), (5.9, 2.4, 1.85), (5.9, 2.6, 1.85), (5.6, 2.6, 1.85)])  # the lamp
    obj = tmp_path / "house.obj"
    obj.write_text("\n".join(lines) + "\n")

    world = matterport.build(model, name="test_house", mesh=obj)
    validate.validate("world", world)
    (top,) = world["anchors"]
    assert top["id"] == "living_room_top_1" and top["kind"] == "surface" and top["source"] == "mesh"
    assert top["point"] == pytest.approx([5.75, 2.5, 0.75], abs=0.03)      # heights are above the floor (0.02 in the mesh)
    xs, ys = [p[0] for p in top["extent"]], [p[1] for p in top["extent"]]
    assert x0 - 0.01 <= min(xs) <= x0 + 0.1 and x1 - 0.1 <= max(xs) <= x1 + 0.01
    assert y0 - 0.01 <= min(ys) <= y0 + 0.1 and y1 - 0.1 <= max(ys) <= y1 + 0.01

    scan = [o for o in world["obstacles"] if o["source"] == "mesh"]
    table = [o for o in scan if o["box"]["min"][2] == 0.0]
    lamp = [o for o in scan if o["box"]["min"][2] > 1.5]
    assert table and lamp and len(scan) == len(table) + len(lamp) <= 6
    assert all(o["room"] == "living_room" for o in scan)
    assert max(o["box"]["max"][2] for o in table) == pytest.approx(0.75, abs=0.02)     # the arm may reach over it
    assert min(o["box"]["min"][0] for o in table) == pytest.approx(x0, abs=0.11)
    assert max(o["box"]["max"][0] for o in table) == pytest.approx(x1, abs=0.11)
