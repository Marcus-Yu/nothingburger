"""Writes world/scenarios/jrr.*: the Rabinowitz atrium traced from the public Matterport tour 2K7G7cdukZV.
Pixel boxes below were read off a 1204 x 999 crop of the tour floor-plan view (floor 2); K is pixels per metre,
from the tour figure for the floor (92 ft 1 in x 75 ft 2 in). Run from the repo root."""
import json
K = 40.8
X = lambda px: round((px - 28) / K, 2)
Y = lambda py: round((975 - py) / K, 2)
def box(x0, y0, x1, y1, h):  # zoom-image pixels: left, top, right, bottom
    return {"min": [X(x0), Y(y1), 0.0], "max": [X(x1), Y(y0), h]}
tables = {  # the orange-clothed folding tables, as seen in the tour's floor plan
 "cloth_table_n1": (490, 358, 567, 396), "cloth_table_n2": (592, 358, 668, 398), "cloth_table_n3": (685, 365, 760, 400),
 "cloth_table_w1": (378, 352, 412, 432), "cloth_table_w2": (378, 445, 412, 520), "cloth_table_w3": (378, 545, 412, 620), "cloth_table_w4": (378, 632, 412, 708),
 "cloth_table_c1": (498, 462, 575, 500), "cloth_table_c2": (600, 470, 678, 505), "cloth_table_c3": (740, 462, 770, 540), "cloth_table_c4": (740, 545, 770, 615),
 "cloth_table_c5": (498, 573, 575, 612), "cloth_table_c6": (597, 570, 672, 603),
 "cloth_table_s1": (425, 702, 503, 737), "cloth_table_s2": (517, 700, 593, 735), "cloth_table_s3": (613, 698, 690, 735), "cloth_table_s4": (718, 695, 795, 730),
 "cloth_table_e1": (880, 295, 918, 370), "cloth_table_e2": (965, 395, 1000, 470), "cloth_table_e3": (965, 545, 1000, 620), "cloth_table_e4": (875, 648, 915, 720)}
TH = 0.74
obst = [{"id": k, "room": "atrium", "box": box(*v, TH)} for k, v in tables.items()]
obst += [{"id": "stairs", "room": "atrium", "box": box(570, 268, 790, 335, 2.0)},
         {"id": "av_corner", "room": "atrium", "box": box(340, 268, 560, 330, 1.2)},
         {"id": "floor_opening_rail", "room": "atrium", "box": box(945, 620, 1025, 770, 1.1)}]
def top(name, tid):
    b = next(o for o in obst if o["id"] == tid)["box"]; lo, hi = b["min"], b["max"]
    return {"id": name, "room": "atrium", "kind": "surface", "point": [round((lo[0] + hi[0]) / 2, 2), round((lo[1] + hi[1]) / 2, 2), TH],
            "normal": [0, 0, 1], "source": "manual", "extent": [[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]}
e2 = next(o for o in obst if o["id"] == "cloth_table_e2")["box"]
ax0, ax1, ay0, ay1 = X(340), X(1025), Y(770), Y(268)
ex1 = X(1145)
world = {
 "schema": "world/1", "id": "jrr",
 "frame": "metres, Z up, right handed; origin at the south-west corner of floor 2's outline in the tour's floor plan, +X east across the picture, +Y up the picture",
 "source": "traced by eye from the public Matterport tour 2K7G7cdukZV (Princeton, Julis Romo Rabinowitz Building, floor 2), not read from the scan: "
           "outlines and tables measured on the tour's floor-plan view and scaled by the tour's own figure for the floor (92 ft 1 in by 75 ft 2 in). "
           "Only the atrium and the east corridor are traced; the corridor ring, chairs and people are left out; heights are assumed",
 "mesh": None,
 "floors": [{"id": "f2", "z": 0.0}],
 "rooms": [
  {"id": "atrium", "type": "atrium", "floor": "f2", "polygon": [[ax0, ay0], [ax1, ay0], [ax1, ay1], [ax0, ay1]], "ceiling_m": 9.0, "source": "manual", "width_m": round(ay1 - ay0, 2)},
  {"id": "east_corridor", "type": "hallway", "floor": "f2", "polygon": [[ax1, 0.0], [ex1, 0.0], [ex1, Y(35)], [ax1, Y(35)]], "ceiling_m": 3.0, "source": "manual", "width_m": round(ex1 - ax1, 2)}],
 "doorways": [
  {"id": "d_south", "rooms": ["outside", "east_corridor"], "position": [round((ax1 + ex1) / 2, 2), 0.0], "along": [1, 0], "width_m": 1.8, "header_m": 2.1, "step_m": 0.0, "source": "manual"},
  {"id": "d_atrium", "rooms": ["east_corridor", "atrium"], "position": [ax1, Y(510)], "along": [0, 1], "width_m": 2.4, "header_m": 3.0, "step_m": 0.0, "source": "manual"}],
 "obstacles": obst,
 "dock": {"room": "east_corridor", "pose": [round((ax1 + ex1) / 2, 2), 2.0, 1.5708]},
 "way_out": {"doorway": "d_south"},
 "anchors": [top("table_c6_top", "cloth_table_c6"), top("table_s3_top", "cloth_table_s3"),
             {"id": "bottle_on_table_e2", "room": "atrium", "kind": "low_item", "point": [round(e2["min"][0] + 0.15, 2), round((e2["min"][1] + e2["max"][1]) / 2, 2), TH + 0.1],
              "normal": [0, 0, 1], "source": "manual"}]}
json.dump(world, open("world/scenarios/jrr.json", "w"), indent=1)
json.dump({"note": "the same job as jrr.job.txt, for runs without a model", "tasks": [
  {"id": "t1", "skill": "wipe", "anchor": "table_c6_top", "object": "cloth", "carries": False},
  {"id": "t2", "skill": "wipe", "anchor": "table_s3_top", "object": "cloth", "carries": False},
  {"id": "t3", "skill": "pick", "anchor": "bottle_on_table_e2", "object": "sample_bottle", "carries": True, "deliver_to": "way_out"}]}, open("world/scenarios/jrr.tasks.json", "w"), indent=1)
open("world/scenarios/jrr.job.txt", "w").write("The hackathon in the Rabinowitz atrium is over. Wipe down the table in the middle of the room and the one in the south row, then pick up the bottle left on the table by the east corridor and take it out through the south door.\n")
print(world["rooms"][0]["polygon"], world["rooms"][1]["polygon"], world["doorways"][1]["position"], world["anchors"][2]["point"])
