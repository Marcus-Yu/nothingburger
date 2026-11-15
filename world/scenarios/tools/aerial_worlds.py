"""Write the outdoor scenarios that are traced on Vexcel aerial photos.

    python world/scenarios/tools/aerial_worlds.py

Each scenario is one real lot. Its photo and footprints were fetched by aerial_fetch.py into
world/scenarios/aerial/ (x east, y north, metres around the fetched point). What the robot can drive on, what
stands in its way and where the job's objects are were read off that photo by eye against a one-metre grid, so
plan positions are good to about 0.2 m. The photo gives no heights and nothing under a roof: every height, every
door and every room inside a building is assumed, and each world's `source` says so.

Writes world/scenarios/<id>.json, <id>.tasks.json and <id>.job.txt, and the studio's picture of the lot
(frontend/assets/aerial/<id with hyphens>.jpg), for:
  lawn_palmetto    mow a back lawn (Houston)
  trash_palmetto   kitchen trash bag out to the bins at the kerb (Houston)
  pooldeck_lakes   wipe a sun lounger and collect a towel on an apartment pool deck (Houston)
  parcel_eastland  bring a parcel from the kerb up the driveway to the front door (Houston)
  lawn_sanpedro    mow a fenced lawn (Los Angeles)
  kerbside_palmetto  three trash bags to the kerb, planned on Vexcel's height survey instead of traced obstacles (Houston)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
AERIAL = HERE / "aerial"
sys.path.insert(0, str(HERE.parents[1]))

from nav import api as nav  # noqa: E402  (the mowing passes: nav/coverage.py)


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def box(id_, room, x0, y0, x1, y1, h, seen=True):
    o = {"id": id_, "room": room, "box": {"min": [x0, y0, 0.0], "max": [x1, y1, h]}}
    if seen:
        o["seen"] = "photo"  # it is in the aerial photo; its height is assumed
    return o


def room(id_, type_, polygon, ceiling=3.0):
    return {"id": id_, "type": type_, "floor": "f0", "polygon": [[float(x), float(y)] for x, y in polygon],
            "ceiling_m": ceiling, "source": "manual"}


def door(id_, rooms, position, along, width, header=2.05, step=0.0):
    return {"id": id_, "rooms": rooms, "position": position, "along": along, "width_m": width, "header_m": header,
            "step_m": step, "source": "manual"}


def anchor(id_, room_, kind, point, **extra):
    return {"id": id_, "room": room_, "kind": kind, "point": point, "normal": [0, 0, 1], "source": "manual", **extra}


def world(id_, site, what, assumed, rooms, doorways, obstacles, dock, way_out, anchors, areas=(), survey=None):
    """`survey`, when given, makes the world's ground the site's height survey (aerial_fetch.py --heights): nav then
    plans on what the survey shows standing, not on traced obstacles. It holds the film's camera ({"azimuth", ...})."""
    s = json.loads((AERIAL / f"{site}.site.json").read_text())
    how = ("measured from Vexcel's aerial survey" if survey is not None else "traced by eye on a Vexcel aerial photo")
    ground = {"image": s["image"], "extent": s["extent"], "m_per_px": s["m_per_px"], "source": s["source"], "lat": s["lat"], "lon": s["lon"]}
    if survey is not None:
        ground |= {"height": s["height"]["file"], "height_source": s["height"]["source"], "dsm": s["height"].get("dsm"), "view": survey}
    return {
        "schema": "world/1", "id": id_, "frame": "metres, Z up, right handed; x east, y north, origin at the fetched point",
        "source": f"{how} ({s['source'].split('collection ')[-1]}, {s['m_per_px']} m a pixel) "
                  f"around {s['lat']}, {s['lon']}: {what}. Assumed, not in the photo: {assumed}",
        "mesh": None,
        "ground": ground,
        "floors": [{"id": "f0", "z": 0.0}],
        "rooms": rooms, "doorways": doorways, "obstacles": obstacles, "dock": dock, "way_out": way_out, "anchors": anchors,
        # ground a job can cover (mowing): the patch and the boxes [x0, y0, x1, y1] its passes keep clear of
        **({"areas": list(areas)} if areas else {}),
    }


# ------------------------------------------------------------------ the five scenarios

def lawn_palmetto():
    lawn = [[-22.6, -17.9], [-7.2, -17.9], [-7.2, -6.0], [-18.6, -6.0], [-18.6, -5.2], [-22.6, -5.2]]
    area = {"id": "lawn", "kind": "lawn", "room": "lawn", "polygon": rect(-22.6, -17.9, -7.2, -6.0), "keep_out": [[-14.75, -9.15, -9.75, -5.0]]}
    w = world("lawn_palmetto", "palmetto",
              "the back lawn of the west house, its fence line on three sides and the house wall on the fourth, and the cluttered patio slab",
              "the patio clutter's height (0.6 m); that the ground is level",
              [room("lawn", "lawn", lawn)], [],
              [box("patio_clutter", "lawn", -14.0, -8.4, -10.5, -6.0, 0.6)],
              {"room": "lawn", "pose": [-8.4, -7.2, math.pi]}, {"doorway": None, "note": "the job stays on the lawn"}, [], [area])
    job = "Mow the back lawn behind the house. Keep off the patio slab, which has things stacked on it, and stay inside the fence."
    return w, [nav.cover(area)], job


def trash_palmetto():
    yard = [[-4.8, 10.9], [-0.7, 10.9], [-0.7, 10.45], [9.4, 10.45], [9.4, 19.6], [-4.8, 19.6]]
    w = world("trash_palmetto", "palmetto",
              "the middle house's front: the lawn, the driveway with the two vehicles parked on it, the pavement, the verge and the kerb where the bins stand",
              "everything under the roof (one room, 3.7 by 4.3 m, behind a front door in the recess beside the garage; where the bag stands in it); "
              "the door's width and its sill (taken as flush); the vehicles' heights",
              [room("kitchen", "kitchen", rect(-4.6, 6.6, -0.9, 10.9), 2.4), room("front_yard", "yard", yard)],
              [door("d_front", ["kitchen", "front_yard"], [-2.7, 10.9], [1, 0], 0.9),
               door("d_kerb", ["outside", "front_yard"], [6.0, 19.6], [1, 0], 1.4, header=9.0)],
              [box("pickup_truck", "front_yard", 0.8, 10.6, 2.9, 15.8, 1.8), box("parked_car", "front_yard", 3.0, 10.9, 5.5, 16.1, 1.5),
               box("trash_bag_body", "kitchen", -1.7, 8.4, -1.3, 8.8, 0.5, seen=False)],
              {"room": "kitchen", "pose": [-3.7, 7.5, math.pi / 2]}, {"doorway": "d_kerb", "note": "the kerb beside the bins seen in the photo"},
              [anchor("trash_bag", "kitchen", "low_item", [-1.5, 8.6, 0.5])])
    tasks = [{"id": "t1", "skill": "pick", "anchor": "trash_bag", "object": "trash_bag", "carries": True, "deliver_to": "way_out"}]
    job = ("Take the kitchen trash bag out to the bins at the kerb: out of the front door, round the truck parked on the driveway, "
           "along the pavement and across the verge.")
    return w, tasks, job


def pooldeck_lakes():
    deck = [[-10.5, 8.3], [-6.3, 8.3], [-6.3, 12.8], [-1.5, 12.8], [-1.5, 14.2], [-5.0, 19.85], [-10.5, 19.85]]
    loungers = [box(f"lounger_{k + 1}", "deck", x - 0.31, 14.1, x + 0.31, 17.0, 0.35)
                for k, x in enumerate((-9.7, -8.95, -8.2, -7.45, -6.7, -5.95, -5.3))]
    w = world("pooldeck_lakes", "lakes610",
              "the pool deck north of the pool: the clubhouse wall on the west, the fence on the north and east, the row of seven sun loungers, "
              "the lounger standing apart from them and the round daybed",
              "every height (lounger tops 0.35 m, daybed 0.45 m); the clubhouse door, which cannot be seen from above and is put on the west wall; "
              "that a towel has been left on the daybed",
              [room("deck", "deck", deck)],
              [door("d_club", ["outside", "deck"], [-10.5, 12.6], [0, 1], 0.9)],
              loungers + [box("lounger_end", "deck", -4.02, 14.3, -3.38, 16.9, 0.35), box("daybed", "deck", -10.45, 9.0, -8.7, 10.8, 0.45)],
              {"room": "deck", "pose": [-9.6, 18.7, -math.pi / 2]}, {"doorway": "d_club", "note": "the clubhouse door (assumed position)"},
              [anchor("lounger_top", "deck", "surface", [-3.7, 15.2, 0.35], extent=rect(-4.0, 14.35, -3.4, 16.05)),
               anchor("towel", "deck", "low_item", [-8.85, 9.9, 0.5])])
    tasks = [{"id": "t1", "skill": "wipe", "anchor": "lounger_top", "object": "cloth", "carries": False},
             {"id": "t2", "skill": "pick", "anchor": "towel", "object": "hand_towel", "carries": True, "deliver_to": "way_out"}]
    job = ("Tidy the pool deck before it opens: wipe down the sun lounger that stands apart at the end of the row, "
           "then pick up the towel left on the daybed and bring it to the clubhouse door.")
    return w, tasks, job


def parcel_eastland():
    w = world("parcel_eastland", "eastland",
              "the concrete driveway of the middle house from its front wall to the street, with the pavement crossing it",
              "the front door (put on the east wall, 0.9 m wide, sill taken as flush); that a parcel has been left at the kerb; the parcel itself",
              [room("driveway", "driveway", rect(6.9, -0.4, 16.4, 3.2))],
              [door("d_front", ["outside", "driveway"], [6.9, 1.4], [0, 1], 0.9)],
              [box("parcel_body", "driveway", 15.28, 0.47, 15.52, 0.53, 0.2, seen=False)],
              {"room": "driveway", "pose": [8.2, 2.4, 0.0]}, {"doorway": "d_front", "note": "the front door (assumed position)"},
              [anchor("parcel", "driveway", "low_item", [15.4, 0.5, 0.2])])
    tasks = [{"id": "t1", "skill": "pick", "anchor": "parcel", "object": "parcel_small", "carries": True, "deliver_to": "way_out"}]
    job = "A small parcel has been left at the kerb, where the driveway meets the street. Bring it up the driveway to the front door."
    return w, tasks, job


def lawn_sanpedro():
    area = {"id": "lawn", "kind": "lawn", "room": "lawn",
            "polygon": [[-13.0, 11.4], [-5.2, 11.4], [-5.2, 19.9], [-6.7, 19.9], [-6.7, 21.8], [-13.0, 21.8]]}
    w = world("lawn_sanpedro", "sanpedro",
              "the fenced lawn between two houses, the concrete path on its west side and the patio slab in its north-east corner",
              "that the ground is level; the slab's edge is taken as flush with the grass",
              [room("lawn", "lawn", rect(-13.0, 11.4, -5.2, 21.8))], [], [],
              {"room": "lawn", "pose": [-5.9, 21.0, math.pi]}, {"doorway": None, "note": "the job stays on the lawn"}, [], [area])
    job = "Mow the lawn between the two houses. The robot starts and finishes on the patio slab in the corner."
    return w, [nav.cover(area)], job


def kerbside_palmetto():
    # by the west house's front wall, behind its tree; in front of the middle house; down the passage beside the east house
    bags = {"a": [-16.0, 9.6], "b": [-2.7, 12.0], "c": [8.0, 7.5]}
    w = world("kerbside_palmetto", "palmetto",
              "nothing is traced: the ground the robot may use is every part of the three front yards where Vexcel's surface model "
              "stands less than 0.15 m above the bare ground, so the houses, trees, fences and the vehicles parked on the driveways "
              "block it as surveyed. The yards stop at the kerb line",
              "that a tied trash bag has been put out in front of each house, and where; the bags' height",
              [room("front_yards", "yard", rect(-26.0, 2.0, 26.0, 19.6))],
              [door("d_kerb", ["outside", "front_yards"], [3.6, 19.6], [1, 0], 1.4, header=9.0)],
              [box(f"trash_bag_{k}_body", "front_yards", x - 0.17, y - 0.17, x + 0.17, y + 0.17, 0.5, seen=False) for k, (x, y) in bags.items()],
              {"room": "front_yards", "pose": [-5.5, 15.5, 0.0]}, {"doorway": "d_kerb", "note": "the kerb, beside the bins the survey shows there"},
              [anchor(f"trash_bag_{k}", "front_yards", "low_item", [x, y, 0.5]) for k, (x, y) in bags.items()],
              survey={"azimuth": -118.0, "elevation": -42.0, "distance": 11.0})
    tasks = [{"id": f"t{i + 1}", "skill": "pick", "anchor": f"trash_bag_{k}", "object": "trash_bag", "carries": True, "deliver_to": "way_out"}
             for i, k in enumerate(bags)]
    job = ("Collection day on the street: take the trash bag put out in front of each of the three houses to the kerb, by the bins. "
           "Stay off the road, and go round whatever is parked on the driveways.")
    return w, tasks, job


SCENARIOS = [lawn_palmetto, trash_palmetto, pooldeck_lakes, parcel_eastland, lawn_sanpedro, kerbside_palmetto]
STUDIO = HERE.parents[1] / "frontend" / "assets" / "aerial"   # the studio's picture of each lot (frontend/space.js)
STUDIO_ASPECT, STUDIO_MARGIN_M, STUDIO_PX = 16 / 9, 5.0, 1920


def studio_image(w: dict) -> Path:
    """The lot as the studio shows it: the photo cut to the world's rooms plus a margin, 16:9, with the ground
    the robot may use outlined and the dock marked. Written to frontend/assets/aerial/<space id>.jpg."""
    from PIL import Image, ImageDraw

    g = w["ground"]
    x0, y0, x1, y1 = g["extent"]
    photo = Image.open(HERE.parents[1] / g["image"]).convert("RGB")
    pts = [p for r in w["rooms"] for p in r["polygon"]]
    cx, cy = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2, (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
    wide = max(max(p[0] for p in pts) - min(p[0] for p in pts) + 2 * STUDIO_MARGIN_M,
               (max(p[1] for p in pts) - min(p[1] for p in pts) + 2 * STUDIO_MARGIN_M) * STUDIO_ASPECT)
    wide = min(wide, x1 - x0, (y1 - y0) * STUDIO_ASPECT)
    high = wide / STUDIO_ASPECT
    cx, cy = min(max(cx, x0 + wide / 2), x1 - wide / 2), min(max(cy, y0 + high / 2), y1 - high / 2)
    sx, sy = photo.size[0] / (x1 - x0), photo.size[1] / (y1 - y0)
    crop = photo.crop((round((cx - wide / 2 - x0) * sx), round((y1 - cy - high / 2) * sy),
                       round((cx + wide / 2 - x0) * sx), round((y1 - cy + high / 2) * sy)))
    img = crop.resize((STUDIO_PX, round(STUDIO_PX / STUDIO_ASPECT)), Image.LANCZOS)
    k = STUDIO_PX / wide

    def px(p):
        return ((p[0] - (cx - wide / 2)) * k, ((cy + high / 2) - p[1]) * k)

    d = ImageDraw.Draw(img, "RGBA")
    for r in w["rooms"]:
        ring = [px(p) for p in r["polygon"]]
        d.line(ring + ring[:1], fill=(255, 255, 255, 235), width=4, joint="curve")
    dx, dy = px(w["dock"]["pose"][:2])
    d.ellipse([dx - 11, dy - 11, dx + 11, dy + 11], fill=(255, 122, 26, 255), outline=(255, 255, 255, 255), width=3)
    out = STUDIO / f"{w['id'].replace('_', '-')}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=86)
    return out

if __name__ == "__main__":
    for make in SCENARIOS:
        w, tasks, job = make()
        (HERE / f"{w['id']}.json").write_text(json.dumps(w, indent=1) + "\n")
        (HERE / f"{w['id']}.tasks.json").write_text(json.dumps({"note": f"the same job as {w['id']}.job.txt, for runs without a model",
                                                                 "tasks": tasks}, indent=1) + "\n")
        (HERE / f"{w['id']}.job.txt").write_text(job + "\n")
        if "height" not in w["ground"]:  # a surveyed world is not a studio space yet
            studio_image(w)
        print(w["id"], "rooms", len(w["rooms"]), "obstacles", len(w["obstacles"]), "tasks", [(t["skill"], len(t.get("waypoints") or [])) for t in tasks])
